"""画布一次生图 / 反推的流水记录，只在调试模式下有内容。

开关关着时这里全程空转：`payload()` 返回 None，接口里就没有 debug 字段，
和加这个功能之前一模一样。所以调用点不用到处套 `if debug_mode`。

不在这里写日志：logger 来自 astrbot，本机跑测试导不进来。
main.py 拿 `log_text()` 自己打。
"""

from __future__ import annotations

import time
from contextlib import contextmanager
from typing import Any, Awaitable, Dict, Iterator, List, Optional

from .api_errors import mask_secrets

# 提示词最长 6000 字，整串塞进调试面板既看不完也撑大存档，截到够看清为止
_VALUE_LIMIT = 2000


def _clean(value: Any) -> Any:
    """字符串脱敏并截断；数字、布尔原样留着，前端好排版。"""
    if isinstance(value, bool) or isinstance(value, (int, float)) or value is None:
        return value

    if isinstance(value, dict):
        return {str(key): _clean(item) for key, item in value.items()}

    text = mask_secrets(str(value))

    if len(text) > _VALUE_LIMIT:
        return f"{text[:_VALUE_LIMIT]}…（共 {len(text)} 字）"

    return text


class DebugTrace:
    """一次任务的耗时与中间值。

    scope 形如 `canvas.generate`，同时用作日志前缀。
    """

    def __init__(self, scope: str, enabled: bool) -> None:
        self.scope = scope
        self.enabled = bool(enabled)
        self._started = time.perf_counter()
        self._stages: List[Dict[str, Any]] = []
        self._notes: Dict[str, Any] = {}

    @contextmanager
    def stage(self, name: str) -> Iterator[None]:
        """记一段耗时。炸了也记——排查时最想知道的就是卡在哪一步炸的。"""
        if not self.enabled:
            yield
            return

        start = time.perf_counter()
        error = ""

        try:
            yield
        except BaseException as exc:  # 取消、超时也要留在流水里，记完照旧往上抛
            error = mask_secrets(f"{type(exc).__name__}: {exc}")
            raise
        finally:
            entry: Dict[str, Any] = {
                "name": name,
                "ms": int((time.perf_counter() - start) * 1000),
            }
            if error:
                entry["error"] = error
            self._stages.append(entry)

    async def timed(self, name: str, awaitable: Awaitable[Any]) -> Any:
        """`stage` 的 await 版，专门给 asyncio.gather 里的并发分支用。"""
        with self.stage(name):
            return await awaitable

    def note(self, key: str, value: Any) -> None:
        if self.enabled:
            self._notes[key] = _clean(value)

    def payload(self) -> Optional[Dict[str, Any]]:
        if not self.enabled:
            return None

        return {
            "scope": self.scope,
            "totalMs": int((time.perf_counter() - self._started) * 1000),
            "stages": list(self._stages),
            "notes": dict(self._notes),
        }

    def log_text(self) -> str:
        """给 logger 用的多行文本，内容和前端面板看到的一致。"""
        data = self.payload()

        if data is None:
            return ""

        lines = [f"[BestNAI/Debug] {data['scope']} 总耗时 {data['totalMs']}ms"]

        for entry in data["stages"]:
            suffix = f" · 失败：{entry['error']}" if entry.get("error") else ""
            lines.append(f"  · {entry['name']} {entry['ms']}ms{suffix}")

        for key, value in data["notes"].items():
            if isinstance(value, dict):
                inner = " ".join(f"{k}={v}" for k, v in value.items())
                lines.append(f"  {key}: {inner}")
            else:
                lines.append(f"  {key}: {value}")

        return "\n".join(lines)
