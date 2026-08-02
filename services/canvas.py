from __future__ import annotations

import base64
import json
import math
import re
from datetime import datetime, timezone
from io import BytesIO
from pathlib import Path
from typing import Any, Awaitable, Callable, Dict, List, Tuple
from uuid import uuid4

from PIL import Image as PILImage

from astrbot.api import logger
from astrbot.api.web import error_response, file_response, json_response, request

from .runtime_state import get_astrbot_plugin_data_dir


GenerateCallback = Callable[
    [Dict[str, Any]],
    Awaitable[Tuple[List[Tuple[str, bytes]], Dict[str, Any]]],
]
ConfigCallback = Callable[[], Dict[str, Any]]
RetagCallback = Callable[[str, str], Awaitable[Dict[str, Any]]]

MAX_NODES = 160
MAX_CONNECTIONS = 320
MAX_WORKSPACE_BYTES = 2 * 1024 * 1024
MAX_UPLOAD_BYTES = 15 * 1024 * 1024
MAX_IMAGE_PIXELS = 30_000_000

ASSET_ID_RE = re.compile(r"^[a-f0-9]{32}$")
NODE_ID_RE = re.compile(r"^[A-Za-z0-9_-]{1,80}$")
ALLOWED_NODE_TYPES = {"prompt", "image", "note"}
FORMAT_EXTENSIONS = {
    "PNG": ".png",
    "JPEG": ".jpg",
    "WEBP": ".webp",
    "GIF": ".gif",
}


class CanvasValidationError(ValueError):
    pass


def _bounded_number(
    value: Any,
    default: float,
    minimum: float,
    maximum: float,
) -> float:
    try:
        number = float(value)
    except (TypeError, ValueError):
        return default

    if not math.isfinite(number):
        return default

    return max(minimum, min(maximum, number))


def _short_text(value: Any, limit: int) -> str:
    return str(value or "")[:limit]


class CanvasStore:
    def __init__(self, plugin_name: str, data_dir: Path | None = None) -> None:
        self.data_dir = (
            Path(data_dir)
            if data_dir is not None
            else get_astrbot_plugin_data_dir(plugin_name) / "canvas"
        )
        self.assets_dir = self.data_dir / "assets"
        self.workspace_path = self.data_dir / "workspace.json"
        self.data_dir.mkdir(parents=True, exist_ok=True)
        self.assets_dir.mkdir(parents=True, exist_ok=True)

    @staticmethod
    def empty_workspace() -> Dict[str, Any]:
        return {
            "version": 1,
            "viewport": {"x": 160.0, "y": 120.0, "scale": 1.0},
            "nodes": [],
            "connections": [],
            "updatedAt": "",
        }

    def sanitize_workspace(self, payload: Any) -> Dict[str, Any]:
        if not isinstance(payload, dict):
            raise CanvasValidationError("工作区数据必须是 JSON 对象")

        raw_nodes = payload.get("nodes", [])
        raw_connections = payload.get("connections", [])

        if not isinstance(raw_nodes, list) or not isinstance(raw_connections, list):
            raise CanvasValidationError("nodes 和 connections 必须是数组")

        if len(raw_nodes) > MAX_NODES:
            raise CanvasValidationError(f"节点数量不能超过 {MAX_NODES}")

        if len(raw_connections) > MAX_CONNECTIONS:
            raise CanvasValidationError(f"连线数量不能超过 {MAX_CONNECTIONS}")

        nodes: List[Dict[str, Any]] = []
        node_ids = set()

        for raw_node in raw_nodes:
            if not isinstance(raw_node, dict):
                raise CanvasValidationError("节点格式错误")

            node_id = str(raw_node.get("id") or "")
            node_type = str(raw_node.get("type") or "")

            if not NODE_ID_RE.fullmatch(node_id) or node_id in node_ids:
                raise CanvasValidationError("节点 ID 无效或重复")

            if node_type not in ALLOWED_NODE_TYPES:
                raise CanvasValidationError(f"不支持的节点类型：{node_type}")

            node_ids.add(node_id)
            asset_id = str(raw_node.get("assetId") or "")

            if asset_id and not ASSET_ID_RE.fullmatch(asset_id):
                raise CanvasValidationError("图片资源 ID 无效")

            raw_meta = raw_node.get("meta", {})
            if not isinstance(raw_meta, dict):
                raw_meta = {}

            node = {
                "id": node_id,
                "type": node_type,
                "x": _bounded_number(raw_node.get("x"), 0, -1_000_000, 1_000_000),
                "y": _bounded_number(raw_node.get("y"), 0, -1_000_000, 1_000_000),
                "width": _bounded_number(raw_node.get("width"), 320, 220, 640),
                "title": _short_text(raw_node.get("title"), 120),
                "prompt": _short_text(raw_node.get("prompt"), 6000),
                "note": _short_text(raw_node.get("note"), 6000),
                "ratio": _short_text(raw_node.get("ratio"), 32),
                "artist": _short_text(raw_node.get("artist"), 120),
                "raw": bool(raw_node.get("raw", False)),
                "assetId": asset_id,
                "createdAt": _short_text(raw_node.get("createdAt"), 64),
                "meta": {
                    "prompt": _short_text(raw_meta.get("prompt"), 6000),
                    "ratio": _short_text(raw_meta.get("ratio"), 32),
                    "width": int(_bounded_number(raw_meta.get("width"), 0, 0, 20_000)),
                    "height": int(_bounded_number(raw_meta.get("height"), 0, 0, 20_000)),
                    "finalPrompt": _short_text(raw_meta.get("finalPrompt"), 6000),
                },
            }
            nodes.append(node)

        connections: List[Dict[str, str]] = []
        seen_connections = set()

        for raw_connection in raw_connections:
            if not isinstance(raw_connection, dict):
                raise CanvasValidationError("连线格式错误")

            source = str(raw_connection.get("source") or "")
            target = str(raw_connection.get("target") or "")
            key = (source, target)

            if (
                source not in node_ids
                or target not in node_ids
                or source == target
                or key in seen_connections
            ):
                continue

            seen_connections.add(key)
            connections.append({"source": source, "target": target})

        raw_viewport = payload.get("viewport", {})
        if not isinstance(raw_viewport, dict):
            raw_viewport = {}

        return {
            "version": 1,
            "viewport": {
                "x": _bounded_number(raw_viewport.get("x"), 160, -1_000_000, 1_000_000),
                "y": _bounded_number(raw_viewport.get("y"), 120, -1_000_000, 1_000_000),
                "scale": _bounded_number(raw_viewport.get("scale"), 1, 0.1, 4),
            },
            "nodes": nodes,
            "connections": connections,
            "updatedAt": datetime.now(timezone.utc).isoformat(),
        }

    def save_workspace(self, payload: Any) -> Dict[str, Any]:
        workspace = self.sanitize_workspace(payload)
        encoded = json.dumps(
            workspace,
            ensure_ascii=False,
            separators=(",", ":"),
        ).encode("utf-8")

        if len(encoded) > MAX_WORKSPACE_BYTES:
            raise CanvasValidationError("工作区数据超过 2 MB 限制")

        temp_path = self.workspace_path.with_suffix(".json.tmp")
        temp_path.write_bytes(encoded)
        temp_path.replace(self.workspace_path)
        return workspace

    def load_workspace(self) -> Dict[str, Any]:
        if not self.workspace_path.exists():
            return self.empty_workspace()

        try:
            if self.workspace_path.stat().st_size > MAX_WORKSPACE_BYTES:
                raise CanvasValidationError("已保存的工作区数据超过大小限制")

            payload = json.loads(self.workspace_path.read_text(encoding="utf-8"))
            return self.sanitize_workspace(payload)
        except CanvasValidationError:
            raise
        except Exception as exc:
            raise CanvasValidationError(f"读取工作区失败：{exc}") from exc

    def store_asset(self, data: bytes, format_hint: str = "") -> Dict[str, Any]:
        if not data:
            raise CanvasValidationError("图片内容为空")

        if len(data) > MAX_UPLOAD_BYTES:
            raise CanvasValidationError("图片不能超过 15 MB")

        try:
            with PILImage.open(BytesIO(data)) as image:
                image_format = str(image.format or format_hint or "").upper()
                width, height = image.size
                image.verify()
        except Exception as exc:
            raise CanvasValidationError("文件不是有效图片") from exc

        if image_format == "JPG":
            image_format = "JPEG"

        if image_format not in FORMAT_EXTENSIONS:
            raise CanvasValidationError("仅支持 PNG、JPEG、WebP 和 GIF 图片")

        if width <= 0 or height <= 0 or width * height > MAX_IMAGE_PIXELS:
            raise CanvasValidationError("图片尺寸无效或像素数超过限制")

        asset_id = uuid4().hex
        asset_path = self.assets_dir / f"{asset_id}{FORMAT_EXTENSIONS[image_format]}"
        asset_path.write_bytes(data)

        return {
            "id": asset_id,
            "format": image_format.lower().replace("jpeg", "jpg"),
            "width": width,
            "height": height,
        }

    def get_asset(self, asset_id: str) -> Tuple[Path, str]:
        if not ASSET_ID_RE.fullmatch(str(asset_id or "")):
            raise CanvasValidationError("图片资源 ID 无效")

        matches = list(self.assets_dir.glob(f"{asset_id}.*"))
        if len(matches) != 1 or not matches[0].is_file():
            raise FileNotFoundError(asset_id)

        suffix = matches[0].suffix.lower()
        mime_type = {
            ".png": "image/png",
            ".jpg": "image/jpeg",
            ".jpeg": "image/jpeg",
            ".webp": "image/webp",
            ".gif": "image/gif",
        }.get(suffix, "application/octet-stream")
        return matches[0], mime_type

    def asset_payload(self, asset_id: str) -> Dict[str, Any]:
        path, mime_type = self.get_asset(asset_id)
        if path.stat().st_size > MAX_UPLOAD_BYTES:
            raise CanvasValidationError("图片资源超过读取限制")

        data_url = f"data:{mime_type};base64,{base64.b64encode(path.read_bytes()).decode()}"
        return {"id": asset_id, "dataUrl": data_url, "mimeType": mime_type}


class CanvasService:
    def __init__(
        self,
        plugin_name: str,
        generate_callback: GenerateCallback,
        config_callback: ConfigCallback,
        retag_callback: RetagCallback | None = None,
        data_dir: Path | None = None,
    ) -> None:
        self.plugin_name = plugin_name
        self.generate_callback = generate_callback
        self.config_callback = config_callback
        self.retag_callback = retag_callback
        self.store = CanvasStore(plugin_name, data_dir=data_dir)

    def register(self, context: Any) -> None:
        prefix = f"/{self.plugin_name}/canvas"
        routes = [
            ("config", self.get_config, ["GET"], "Infinite Canvas：获取配置"),
            ("generate", self.generate, ["POST"], "Infinite Canvas：生成图片"),
            ("retag", self.retag, ["POST"], "Infinite Canvas：反推图片提示词"),
            ("workspace", self.load_workspace, ["GET"], "Infinite Canvas：加载工作区"),
            ("workspace", self.save_workspace, ["POST"], "Infinite Canvas：保存工作区"),
            ("workspace/import", self.import_workspace, ["POST"], "Infinite Canvas：导入工作区"),
            ("workspace/export", self.export_workspace, ["GET"], "Infinite Canvas：导出工作区"),
            ("upload", self.upload_asset, ["POST"], "Infinite Canvas：上传图片"),
            ("asset", self.get_asset, ["GET"], "Infinite Canvas：读取图片"),
        ]

        for suffix, handler, methods, description in routes:
            context.register_web_api(
                f"{prefix}/{suffix}",
                handler,
                methods,
                description,
            )

    async def get_config(self) -> Any:
        return json_response(self.config_callback())

    async def generate(self) -> Any:
        payload = await request.json(default={})
        if not isinstance(payload, dict):
            return error_response("请求体必须是 JSON 对象", status_code=400)

        try:
            images, metadata = await self.generate_callback(payload)
            assets = []

            for image_format, image_bytes in images:
                asset = self.store.store_asset(image_bytes, image_format)
                asset.update(self.store.asset_payload(asset["id"]))
                assets.append(asset)

            return json_response({"assets": assets, "meta": metadata})
        except CanvasValidationError as exc:
            return error_response(str(exc), status_code=400)
        except ValueError as exc:
            return error_response(str(exc), status_code=422)
        except Exception as exc:
            logger.exception(f"[BestNAI/Canvas] 生成失败: {exc}")
            message = getattr(exc, "message", None) or str(exc) or "生成失败"
            return error_response(message, status_code=502)

    async def retag(self) -> Any:
        payload = await request.json(default={})
        if not isinstance(payload, dict):
            return error_response("请求体必须是 JSON 对象", status_code=400)

        asset_id = str(payload.get("assetId") or "")
        user_hint = _short_text(payload.get("userHint"), 6000).strip()

        try:
            if self.retag_callback is None:
                raise ValueError("画布图片反推服务不可用")

            asset_path, _ = self.store.get_asset(asset_id)
            result = await self.retag_callback(str(asset_path), user_hint)
            return json_response(result)
        except FileNotFoundError:
            return error_response("图片资源不存在", status_code=404)
        except CanvasValidationError as exc:
            return error_response(str(exc), status_code=400)
        except ValueError as exc:
            return error_response(str(exc), status_code=422)
        except Exception as exc:
            logger.exception(f"[BestNAI/Canvas] 图片反推失败: {exc}")
            message = getattr(exc, "message", None) or str(exc) or "图片反推失败"
            return error_response(message, status_code=502)

    async def load_workspace(self) -> Any:
        try:
            return json_response(self.store.load_workspace())
        except CanvasValidationError as exc:
            return error_response(str(exc), status_code=500)

    async def save_workspace(self) -> Any:
        payload = await request.json(default={})
        try:
            workspace = self.store.save_workspace(payload)
            return json_response({"saved": True, "updatedAt": workspace["updatedAt"]})
        except CanvasValidationError as exc:
            return error_response(str(exc), status_code=400)
        except Exception as exc:
            logger.exception(f"[BestNAI/Canvas] 保存工作区失败: {exc}")
            return error_response("保存工作区失败", status_code=500)

    async def upload_asset(self) -> Any:
        try:
            files = await request.files()
            upload = files.get("file")
            if upload is None:
                return error_response("请选择图片文件", status_code=400)

            if upload.content_length and upload.content_length > MAX_UPLOAD_BYTES:
                return error_response("图片不能超过 15 MB", status_code=413)

            data = await upload.read(MAX_UPLOAD_BYTES + 1)
            asset = self.store.store_asset(data)
            asset.update(self.store.asset_payload(asset["id"]))
            return json_response(asset)
        except CanvasValidationError as exc:
            return error_response(str(exc), status_code=400)
        except Exception as exc:
            logger.exception(f"[BestNAI/Canvas] 上传图片失败: {exc}")
            return error_response("上传图片失败", status_code=500)

    async def get_asset(self) -> Any:
        asset_id = str(request.query.get("id", "") or "")
        try:
            return json_response(self.store.asset_payload(asset_id))
        except FileNotFoundError:
            return error_response("图片资源不存在", status_code=404)
        except CanvasValidationError as exc:
            return error_response(str(exc), status_code=400)

    async def export_workspace(self) -> Any:
        if not self.store.workspace_path.exists():
            self.store.save_workspace(self.store.empty_workspace())

        return file_response(
            self.store.workspace_path,
            filename="bestnai-canvas.json",
            content_type="application/json",
        )

    async def import_workspace(self) -> Any:
        try:
            files = await request.files()
            upload = files.get("file")
            if upload is None:
                return error_response("请选择工作区 JSON 文件", status_code=400)

            if upload.content_length and upload.content_length > MAX_WORKSPACE_BYTES:
                return error_response("工作区文件不能超过 2 MB", status_code=413)

            raw = await upload.read(MAX_WORKSPACE_BYTES + 1)
            if len(raw) > MAX_WORKSPACE_BYTES:
                return error_response("工作区文件不能超过 2 MB", status_code=413)

            payload = json.loads(raw.decode("utf-8-sig"))
            workspace = self.store.save_workspace(payload)
            return json_response(workspace)
        except (UnicodeDecodeError, json.JSONDecodeError):
            return error_response("文件不是有效的 JSON", status_code=400)
        except CanvasValidationError as exc:
            return error_response(str(exc), status_code=400)
        except Exception as exc:
            logger.exception(f"[BestNAI/Canvas] 导入工作区失败: {exc}")
            return error_response("导入工作区失败", status_code=500)
