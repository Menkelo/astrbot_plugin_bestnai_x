"""DanbooruTagRetriever 主/备端点故障转移测试。

主端点（HF Space）无流量休眠后冷启动要 30~60 秒，请求会失败或超时；
镜像端点应自动接住，检索不能整段不可用。
"""

from __future__ import annotations

import asyncio
import sys
import unittest
from pathlib import Path


workspace_dir = Path(__file__).resolve().parents[2]
if str(workspace_dir) not in sys.path:
    sys.path.insert(0, str(workspace_dir))

# 其他测试为跳过真实 HTTP 会给 aiohttp 装裸模块桩；本测试要起本地服务器，
# 必须确保 sys.modules 里是真实的 aiohttp（桩已装则换成真包再导入插件）。
_existing_aiohttp = sys.modules.get("aiohttp")
if _existing_aiohttp is not None and not hasattr(_existing_aiohttp, "ClientSession"):
    del sys.modules["aiohttp"]

from aiohttp import web  # noqa: E402

from astrbot_plugin_bestnai_x.core.translator import (  # noqa: E402
    DANBOORU_SEARCH_BACKUP_API_URL,
    DanbooruTagRetriever,
)


def _search_payload() -> dict:
    return {
        "results": [
            {"tag": "hatsune_miku", "cn_name": "初音未来", "final_score": 0.9},
            {"tag": "twintails", "cn_name": "双马尾", "final_score": 0.8},
        ]
    }


def _related_payload() -> dict:
    return {"results": [{"tag": "green_hair", "cn_name": "绿发", "cooc_score": 0.7}]}


class _Server:
    def __init__(self, handler) -> None:
        self._runner: web.AppRunner | None = None
        self._handler = handler

    async def start(self) -> str:
        app = web.Application()
        app.router.add_route("*", "/{tail:.*}", self._handler)
        self._runner = web.AppRunner(app)
        await self._runner.setup()
        site = web.TCPSite(self._runner, "127.0.0.1", 0)
        await site.start()
        # TCPSite 不直接暴露端口，从 runner 的 socket 拿
        sockets = list(self._runner.addresses)
        host, port = sockets[0][:2]
        return f"http://{host}:{port}"

    async def stop(self) -> None:
        if self._runner is not None:
            await self._runner.cleanup()


async def _always_500(request: web.Request) -> web.Response:
    return web.Response(status=500, text="primary asleep (cold start)")


async def _healthy(request: web.Request) -> web.Response:
    path = request.path
    if path.startswith("/api/search"):
        return web.json_response(_search_payload())
    if path.startswith("/api/related"):
        return web.json_response(_related_payload())
    return web.json_response({})


async def _run_scenario(primary_handler, backup_handler, *, call_retriever):
    primary = _Server(primary_handler)
    backup = _Server(backup_handler)
    primary_url = await primary.start()
    backup_url = await backup.start()
    try:
        retriever = DanbooruTagRetriever(
            base_url=primary_url,
            timeout=5.0,
            backup_url=backup_url,
        )
        return await call_retriever(retriever)
    finally:
        await primary.stop()
        await backup.stop()


class DanbooruFailoverTest(unittest.TestCase):
    def test_retrieve_falls_back_to_mirror_when_primary_fails(self) -> None:
        async def scenario(retriever: DanbooruTagRetriever):
            return await retriever.retrieve("双马尾的虚拟歌手")

        results = asyncio.run(
            _run_scenario(_always_500, _healthy, call_retriever=scenario)
        )

        self.assertEqual(
            [item["tag"] for item in results["search"]],
            ["hatsune_miku", "twintails"],
        )
        # /api/related 同样走镜像
        self.assertEqual(
            [item["tag"] for item in results["related"]],
            ["green_hair"],
        )

    def test_lookup_tags_falls_back_to_mirror(self) -> None:
        async def scenario(retriever: DanbooruTagRetriever):
            return await retriever.lookup_tags(["hatsune_miku", "twintails"])

        result = asyncio.run(
            _run_scenario(_always_500, _healthy, call_retriever=scenario)
        )

        self.assertEqual(
            {item["tag"] for item in result["items"]},
            {"hatsune_miku", "twintails"},
        )
        self.assertIn("hatsune_miku", " ".join(result["translations"].keys()))

    def test_both_endpoints_down_returns_empty_results(self) -> None:
        async def scenario(retriever: DanbooruTagRetriever):
            return await retriever.retrieve("什么都没有")

        results = asyncio.run(
            _run_scenario(_always_500, _always_500, call_retriever=scenario)
        )

        self.assertEqual(results, {"search": [], "related": []})

    def test_primary_success_never_touches_mirror(self) -> None:
        hits: list[str] = []

        async def healthy_primary(request: web.Request) -> web.Response:
            hits.append(request.path)
            return await _healthy(request)

        async def fail_backup(request: web.Request) -> web.Response:
            raise AssertionError("镜像端点不应被请求")

        async def scenario(retriever: DanbooruTagRetriever):
            return await retriever.retrieve("双马尾")

        asyncio.run(
            _run_scenario(healthy_primary, fail_backup, call_retriever=scenario)
        )

        self.assertEqual(hits, ["/api/search", "/api/related"])

    def test_default_backup_is_the_public_mirror(self) -> None:
        retriever = DanbooruTagRetriever("https://example.invalid")
        self.assertEqual(retriever.backup_url, DANBOORU_SEARCH_BACKUP_API_URL)
        # 同一个地址不重复出现在端点列表里
        retriever = DanbooruTagRetriever(
            "https://sakizuki-danboorusearchonline.ms.show"
        )
        self.assertEqual(
            retriever._endpoints(),
            ["https://sakizuki-danboorusearchonline.ms.show"],
        )


if __name__ == "__main__":
    unittest.main()
