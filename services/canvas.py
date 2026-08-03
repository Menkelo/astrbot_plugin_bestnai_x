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
RetagCallback = Callable[[str, str, bool, str], Awaitable[Dict[str, Any]]]

MAX_NODES = 160
MAX_CONNECTIONS = 320
MAX_WORKSPACE_BYTES = 2 * 1024 * 1024
MAX_UPLOAD_BYTES = 15 * 1024 * 1024
MAX_IMAGE_PIXELS = 30_000_000

ASSET_ID_RE = re.compile(r"^[a-f0-9]{32}$")
ENTITY_ID_RE = re.compile(r"^(?:default|[a-f0-9]{32})$")
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
        self.workspaces_dir = self.data_dir / "workspaces"
        self.projects_path = self.data_dir / "projects.json"
        self.canvases_path = self.data_dir / "canvases.json"
        self.library_path = self.data_dir / "library.json"
        self.preferences_path = self.data_dir / "preferences.json"
        self.data_dir.mkdir(parents=True, exist_ok=True)
        self.assets_dir.mkdir(parents=True, exist_ok=True)
        self.workspaces_dir.mkdir(parents=True, exist_ok=True)
        self._ensure_collections()

    @staticmethod
    def _timestamp() -> str:
        return datetime.now(timezone.utc).isoformat()

    @staticmethod
    def _read_json(path: Path, fallback: Any) -> Any:
        if not path.exists():
            return fallback
        try:
            return json.loads(path.read_text(encoding="utf-8"))
        except Exception as exc:
            raise CanvasValidationError(f"读取 {path.name} 失败：{exc}") from exc

    @staticmethod
    def _write_json(path: Path, payload: Any) -> None:
        encoded = json.dumps(payload, ensure_ascii=False, separators=(",", ":")).encode("utf-8")
        temp_path = path.with_suffix(path.suffix + ".tmp")
        temp_path.write_bytes(encoded)
        temp_path.replace(path)

    def _ensure_collections(self) -> None:
        now = self._timestamp()
        if not self.projects_path.exists():
            self._write_json(
                self.projects_path,
                {"projects": [{"id": "default", "name": "默认项目", "order": 0, "createdAt": now}]},
            )
        if not self.canvases_path.exists():
            canvases: List[Dict[str, Any]] = []
            if self.workspace_path.exists():
                canvas_id = uuid4().hex
                try:
                    workspace = self.sanitize_workspace(
                        json.loads(self.workspace_path.read_text(encoding="utf-8"))
                    )
                except Exception:
                    workspace = self.empty_workspace()
                self._write_json(self.workspaces_dir / f"{canvas_id}.json", workspace)
                canvases.append(
                    {
                        "id": canvas_id,
                        "title": "迁移画布",
                        "projectId": "default",
                        "x": 120.0,
                        "y": 100.0,
                        "kind": "classic",
                        "nodeCount": len(workspace.get("nodes", [])),
                        "createdAt": now,
                        "updatedAt": workspace.get("updatedAt") or now,
                        "deletedAt": "",
                    }
                )
            self._write_json(self.canvases_path, {"canvases": canvases})
        if not self.library_path.exists():
            self._write_json(self.library_path, {"images": [], "prompts": []})
        if not self.preferences_path.exists():
            self._write_json(
                self.preferences_path,
                {"lastCanvasId": "", "ratio": "", "artist": ""},
            )

    def _projects(self) -> List[Dict[str, Any]]:
        payload = self._read_json(self.projects_path, {"projects": []})
        return payload.get("projects", []) if isinstance(payload, dict) else []

    def _canvases(self) -> List[Dict[str, Any]]:
        payload = self._read_json(self.canvases_path, {"canvases": []})
        return payload.get("canvases", []) if isinstance(payload, dict) else []

    def _library(self) -> Dict[str, List[Dict[str, Any]]]:
        payload = self._read_json(self.library_path, {"images": [], "prompts": []})
        if not isinstance(payload, dict):
            return {"images": [], "prompts": []}
        return {
            "images": payload.get("images", []) if isinstance(payload.get("images"), list) else [],
            "prompts": payload.get("prompts", []) if isinstance(payload.get("prompts"), list) else [],
        }

    def load_preferences(self) -> Dict[str, str]:
        payload = self._read_json(self.preferences_path, {})
        if not isinstance(payload, dict):
            payload = {}
        last_canvas_id = _short_text(payload.get("lastCanvasId"), 32)
        active_canvas_ids = {item.get("id") for item in self.list_canvases()}
        if last_canvas_id not in active_canvas_ids:
            last_canvas_id = ""
        return {
            "lastCanvasId": last_canvas_id,
            "ratio": _short_text(payload.get("ratio"), 32),
            "artist": _short_text(payload.get("artist"), 120),
        }

    def save_preferences(self, payload: Any) -> Dict[str, str]:
        if not isinstance(payload, dict):
            raise CanvasValidationError("画布偏好必须是 JSON 对象")
        current = self.load_preferences()
        if "lastCanvasId" in payload:
            last_canvas_id = _short_text(payload.get("lastCanvasId"), 32)
            active_canvas_ids = {item.get("id") for item in self.list_canvases()}
            current["lastCanvasId"] = last_canvas_id if last_canvas_id in active_canvas_ids else ""
        if "ratio" in payload:
            current["ratio"] = _short_text(payload.get("ratio"), 32)
        if "artist" in payload:
            current["artist"] = _short_text(payload.get("artist"), 120)
        self._write_json(self.preferences_path, current)
        return current

    @staticmethod
    def _validate_entity_id(value: Any, label: str) -> str:
        entity_id = str(value or "")
        if not ENTITY_ID_RE.fullmatch(entity_id):
            raise CanvasValidationError(f"{label} ID 无效")
        return entity_id

    def list_projects(self) -> List[Dict[str, Any]]:
        canvases = self._canvases()
        result = []
        for project in sorted(self._projects(), key=lambda item: int(item.get("order", 0))):
            item = dict(project)
            item["canvasCount"] = sum(
                1
                for canvas in canvases
                if canvas.get("projectId") == project.get("id") and not canvas.get("deletedAt")
            )
            result.append(item)
        return result

    def create_project(self, name: Any) -> Dict[str, Any]:
        projects = self._projects()
        project = {
            "id": uuid4().hex,
            "name": _short_text(name, 60).strip() or "新项目",
            "order": len(projects),
            "createdAt": self._timestamp(),
        }
        projects.append(project)
        self._write_json(self.projects_path, {"projects": projects})
        return {**project, "canvasCount": 0}

    def update_project(self, project_id: Any, name: Any) -> Dict[str, Any]:
        project_id = self._validate_entity_id(project_id, "项目")
        projects = self._projects()
        project = next((item for item in projects if item.get("id") == project_id), None)
        if project is None:
            raise FileNotFoundError(project_id)
        project["name"] = _short_text(name, 60).strip() or project.get("name") or "未命名项目"
        self._write_json(self.projects_path, {"projects": projects})
        return dict(project)

    def delete_project(self, project_id: Any) -> None:
        project_id = self._validate_entity_id(project_id, "项目")
        if project_id == "default":
            raise CanvasValidationError("默认项目不能删除")
        projects = self._projects()
        if not any(item.get("id") == project_id for item in projects):
            raise FileNotFoundError(project_id)
        projects = [item for item in projects if item.get("id") != project_id]
        canvases = self._canvases()
        for canvas in canvases:
            if canvas.get("projectId") == project_id:
                canvas["projectId"] = "default"
        self._write_json(self.projects_path, {"projects": projects})
        self._write_json(self.canvases_path, {"canvases": canvases})

    def list_canvases(self, include_deleted: bool = False) -> List[Dict[str, Any]]:
        items = self._canvases()
        if include_deleted:
            return [dict(item) for item in items if item.get("deletedAt")]
        return [dict(item) for item in items if not item.get("deletedAt")]

    def create_canvas(self, payload: Any) -> Dict[str, Any]:
        if not isinstance(payload, dict):
            payload = {}
        project_id = self._validate_entity_id(payload.get("projectId") or "default", "项目")
        if not any(item.get("id") == project_id for item in self._projects()):
            raise FileNotFoundError(project_id)
        canvas_id = uuid4().hex
        now = self._timestamp()
        canvas = {
            "id": canvas_id,
            "title": _short_text(payload.get("title"), 120).strip() or "未命名画布",
            "projectId": project_id,
            "x": _bounded_number(payload.get("x"), 120, -1_000_000, 1_000_000),
            "y": _bounded_number(payload.get("y"), 100, -1_000_000, 1_000_000),
            "kind": "classic",
            "nodeCount": 0,
            "createdAt": now,
            "updatedAt": now,
            "deletedAt": "",
        }
        canvases = self._canvases()
        canvases.append(canvas)
        self._write_json(self.canvases_path, {"canvases": canvases})
        self._write_json(self.workspaces_dir / f"{canvas_id}.json", self.empty_workspace())
        return dict(canvas)

    def update_canvas(self, payload: Any) -> Dict[str, Any]:
        if not isinstance(payload, dict):
            raise CanvasValidationError("画布更新数据必须是 JSON 对象")
        canvas_id = self._validate_entity_id(payload.get("id"), "画布")
        canvases = self._canvases()
        canvas = next((item for item in canvases if item.get("id") == canvas_id), None)
        if canvas is None:
            raise FileNotFoundError(canvas_id)
        if "title" in payload:
            canvas["title"] = _short_text(payload.get("title"), 120).strip() or canvas.get("title")
        if "projectId" in payload:
            project_id = self._validate_entity_id(payload.get("projectId"), "项目")
            if not any(item.get("id") == project_id for item in self._projects()):
                raise FileNotFoundError(project_id)
            canvas["projectId"] = project_id
        if "x" in payload:
            canvas["x"] = _bounded_number(payload.get("x"), canvas.get("x", 0), -1_000_000, 1_000_000)
        if "y" in payload:
            canvas["y"] = _bounded_number(payload.get("y"), canvas.get("y", 0), -1_000_000, 1_000_000)
        canvas["updatedAt"] = self._timestamp()
        self._write_json(self.canvases_path, {"canvases": canvases})
        return dict(canvas)

    def trash_canvas(self, canvas_id: Any) -> None:
        self._set_canvas_deleted(canvas_id, self._timestamp())

    def restore_canvas(self, canvas_id: Any) -> None:
        self._set_canvas_deleted(canvas_id, "")

    def _set_canvas_deleted(self, canvas_id: Any, deleted_at: str) -> None:
        canvas_id = self._validate_entity_id(canvas_id, "画布")
        canvases = self._canvases()
        canvas = next((item for item in canvases if item.get("id") == canvas_id), None)
        if canvas is None:
            raise FileNotFoundError(canvas_id)
        canvas["deletedAt"] = deleted_at
        canvas["updatedAt"] = self._timestamp()
        self._write_json(self.canvases_path, {"canvases": canvases})

    def purge_canvas(self, canvas_id: Any) -> None:
        canvas_id = self._validate_entity_id(canvas_id, "画布")
        canvases = self._canvases()
        canvas = next((item for item in canvases if item.get("id") == canvas_id), None)
        if canvas is None or not canvas.get("deletedAt"):
            raise FileNotFoundError(canvas_id)
        self._write_json(
            self.canvases_path,
            {"canvases": [item for item in canvases if item.get("id") != canvas_id]},
        )
        workspace_path = self.workspaces_dir / f"{canvas_id}.json"
        if workspace_path.exists():
            workspace_path.unlink()

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
                "height": _bounded_number(raw_node.get("height"), 0, 0, 800),
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
                    "tags": _short_text(raw_meta.get("tags"), 6000),
                    "artist": _short_text(raw_meta.get("artist"), 120),
                    "translatedPrompt": _short_text(raw_meta.get("translatedPrompt"), 6000),
                    "translationSource": _short_text(raw_meta.get("translationSource"), 6000),
                    "translationResult": _short_text(raw_meta.get("translationResult"), 6000),
                    "translatedPromptExpanded": bool(
                        raw_meta.get("translatedPromptExpanded", False)
                    ),
                    "promptCollapsedHeight": int(
                        _bounded_number(raw_meta.get("promptCollapsedHeight"), 0, 0, 800)
                    ),
                    "retagBasePrompt": _short_text(raw_meta.get("retagBasePrompt"), 6000),
                    "retagPrompt": _short_text(raw_meta.get("retagPrompt"), 6000),
                    "retagMergedPrompt": _short_text(raw_meta.get("retagMergedPrompt"), 6000),
                    "retagAssetId": _short_text(raw_meta.get("retagAssetId"), 128),
                    "retagRatio": _short_text(raw_meta.get("retagRatio"), 32),
                    "retagCharacterKeep": bool(raw_meta.get("retagCharacterKeep", False)),
                    "retagCharacterName": _short_text(raw_meta.get("retagCharacterName"), 120),
                    "retagged": bool(raw_meta.get("retagged", False)),
                    "characterKeep": bool(raw_meta.get("characterKeep", False)),
                    "characterName": _short_text(raw_meta.get("characterName"), 120),
                    "userResized": bool(raw_meta.get("userResized", False)),
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

    def _workspace_file(self, canvas_id: str | None = None) -> Path:
        if canvas_id is None:
            return self.workspace_path
        canvas_id = self._validate_entity_id(canvas_id, "画布")
        if canvas_id == "default":
            raise CanvasValidationError("画布 ID 无效")
        if not any(item.get("id") == canvas_id for item in self._canvases()):
            raise FileNotFoundError(canvas_id)
        return self.workspaces_dir / f"{canvas_id}.json"

    def save_workspace(self, payload: Any, canvas_id: str | None = None) -> Dict[str, Any]:
        workspace = self.sanitize_workspace(payload)
        encoded = json.dumps(
            workspace,
            ensure_ascii=False,
            separators=(",", ":"),
        ).encode("utf-8")

        if len(encoded) > MAX_WORKSPACE_BYTES:
            raise CanvasValidationError("工作区数据超过 2 MB 限制")

        workspace_path = self._workspace_file(canvas_id)
        temp_path = workspace_path.with_suffix(".json.tmp")
        temp_path.write_bytes(encoded)
        temp_path.replace(workspace_path)
        if canvas_id is not None:
            canvases = self._canvases()
            canvas = next((item for item in canvases if item.get("id") == canvas_id), None)
            if canvas is not None:
                canvas["nodeCount"] = len(workspace["nodes"])
                canvas["updatedAt"] = workspace["updatedAt"]
                self._write_json(self.canvases_path, {"canvases": canvases})
        return workspace

    def load_workspace(self, canvas_id: str | None = None) -> Dict[str, Any]:
        workspace_path = self._workspace_file(canvas_id)
        if not workspace_path.exists():
            return self.empty_workspace()

        try:
            if workspace_path.stat().st_size > MAX_WORKSPACE_BYTES:
                raise CanvasValidationError("已保存的工作区数据超过大小限制")

            payload = json.loads(workspace_path.read_text(encoding="utf-8"))
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

    def list_library(self) -> Dict[str, List[Dict[str, Any]]]:
        library = self._library()
        return {
            "images": [
                dict(item)
                for item in library["images"]
                if item.get("source") not in {"generation", "upload"}
            ],
            "prompts": [dict(item) for item in library["prompts"]],
        }

    def add_image_to_library(
        self,
        asset: Dict[str, Any],
        name: Any = "",
        source: Any = "",
        prompt: Any = "",
        tags: Any = "",
        ratio: Any = "",
        artist: Any = "",
    ) -> Dict[str, Any]:
        asset_id = str(asset.get("id") or "")
        if not ASSET_ID_RE.fullmatch(asset_id):
            raise CanvasValidationError("图片资源 ID 无效")
        library = self._library()
        existing = next((item for item in library["images"] if item.get("id") == asset_id), None)
        entry = existing or {"id": asset_id, "createdAt": self._timestamp()}
        entry.update(
            {
                "name": _short_text(name, 160).strip() or entry.get("name") or f"图片 {asset_id[:8]}",
                "width": int(_bounded_number(asset.get("width"), entry.get("width", 0), 0, 20_000)),
                "height": int(_bounded_number(asset.get("height"), entry.get("height", 0), 0, 20_000)),
                "format": _short_text(asset.get("format"), 16),
                "source": _short_text(source, 80),
                "prompt": _short_text(prompt, 6000),
                "tags": _short_text(tags, 6000),
                "artist": _short_text(artist, 120),
                "ratio": _short_text(ratio, 32),
            }
        )
        if existing is None:
            library["images"].insert(0, entry)
        self._write_json(self.library_path, library)
        return dict(entry)

    def remove_image_from_library(self, asset_id: Any) -> None:
        asset_id = str(asset_id or "")
        if not ASSET_ID_RE.fullmatch(asset_id):
            raise CanvasValidationError("图片资源 ID 无效")
        library = self._library()
        library["images"] = [item for item in library["images"] if item.get("id") != asset_id]
        self._write_json(self.library_path, library)

    def save_prompt_asset(self, payload: Any) -> Dict[str, Any]:
        if not isinstance(payload, dict):
            raise CanvasValidationError("提示词素材必须是 JSON 对象")
        prompt = _short_text(payload.get("prompt"), 6000).strip()
        if not prompt:
            raise CanvasValidationError("提示词不能为空")
        library = self._library()
        prompt_id = str(payload.get("id") or "")
        entry = None
        if prompt_id:
            if not ENTITY_ID_RE.fullmatch(prompt_id) or prompt_id == "default":
                raise CanvasValidationError("提示词素材 ID 无效")
            entry = next((item for item in library["prompts"] if item.get("id") == prompt_id), None)
        if entry is None:
            entry = {"id": uuid4().hex, "createdAt": self._timestamp()}
            library["prompts"].insert(0, entry)
        entry.update(
            {
                "name": _short_text(payload.get("name"), 120).strip() or prompt[:32],
                "prompt": prompt,
                "ratio": _short_text(payload.get("ratio"), 32),
                "artist": _short_text(payload.get("artist"), 120),
                "raw": bool(payload.get("raw", False)),
                "updatedAt": self._timestamp(),
            }
        )
        self._write_json(self.library_path, library)
        return dict(entry)

    def delete_prompt_asset(self, prompt_id: Any) -> None:
        prompt_id = self._validate_entity_id(prompt_id, "提示词素材")
        if prompt_id == "default":
            raise CanvasValidationError("提示词素材 ID 无效")
        library = self._library()
        library["prompts"] = [item for item in library["prompts"] if item.get("id") != prompt_id]
        self._write_json(self.library_path, library)


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
            ("health", self.health, ["GET"], "Infinite Canvas：连接状态检测"),
            ("config", self.get_config, ["GET"], "Infinite Canvas：获取配置"),
            ("preferences", self.get_preferences, ["GET"], "Infinite Canvas：获取用户偏好"),
            ("preferences", self.save_preferences, ["POST"], "Infinite Canvas：保存用户偏好"),
            ("generate", self.generate, ["POST"], "Infinite Canvas：生成图片"),
            ("retag", self.retag, ["POST"], "Infinite Canvas：反推图片提示词"),
            ("workspace", self.load_workspace, ["GET"], "Infinite Canvas：加载工作区"),
            ("workspace", self.save_workspace, ["POST"], "Infinite Canvas：保存工作区"),
            ("workspace/import", self.import_workspace, ["POST"], "Infinite Canvas：导入工作区"),
            ("workspace/export", self.export_workspace, ["GET"], "Infinite Canvas：导出工作区"),
            ("upload", self.upload_asset, ["POST"], "Infinite Canvas：上传图片"),
            ("asset", self.get_asset, ["GET"], "Infinite Canvas：读取图片"),
            ("asset/download", self.download_asset, ["GET"], "Infinite Canvas：下载图片"),
            ("projects", self.list_projects, ["GET"], "Infinite Canvas：项目列表"),
            ("projects/create", self.create_project, ["POST"], "Infinite Canvas：创建项目"),
            ("projects/update", self.update_project, ["POST"], "Infinite Canvas：更新项目"),
            ("projects/delete", self.delete_project, ["POST"], "Infinite Canvas：删除项目"),
            ("canvases", self.list_canvases, ["GET"], "Infinite Canvas：画布列表"),
            ("canvases/create", self.create_canvas, ["POST"], "Infinite Canvas：创建画布"),
            ("canvases/update", self.update_canvas, ["POST"], "Infinite Canvas：更新画布"),
            ("canvases/delete", self.delete_canvas, ["POST"], "Infinite Canvas：移入回收站"),
            ("canvases/restore", self.restore_canvas, ["POST"], "Infinite Canvas：恢复画布"),
            ("canvases/purge", self.purge_canvas, ["POST"], "Infinite Canvas：彻底删除画布"),
            ("library", self.get_library, ["GET"], "Infinite Canvas：读取素材库"),
            ("library/image/add", self.add_library_image, ["POST"], "Infinite Canvas：收藏图片"),
            ("library/image/delete", self.delete_library_image, ["POST"], "Infinite Canvas：移除图片素材"),
            ("library/prompt/save", self.save_library_prompt, ["POST"], "Infinite Canvas：保存提示词素材"),
            ("library/prompt/delete", self.delete_library_prompt, ["POST"], "Infinite Canvas：删除提示词素材"),
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

    async def get_preferences(self) -> Any:
        try:
            return json_response(self.store.load_preferences())
        except CanvasValidationError as exc:
            return error_response(str(exc), status_code=500)

    async def save_preferences(self) -> Any:
        payload = await request.json(default={})
        try:
            return json_response(self.store.save_preferences(payload))
        except CanvasValidationError as exc:
            return error_response(str(exc), status_code=400)

    async def health(self) -> Any:
        return json_response({"status": "ok"})

    async def list_projects(self) -> Any:
        try:
            return json_response({"projects": self.store.list_projects()})
        except CanvasValidationError as exc:
            return error_response(str(exc), status_code=500)

    async def create_project(self) -> Any:
        payload = await request.json(default={})
        if not isinstance(payload, dict):
            return error_response("请求体必须是 JSON 对象", status_code=400)
        try:
            return json_response({"project": self.store.create_project(payload.get("name"))})
        except CanvasValidationError as exc:
            return error_response(str(exc), status_code=400)

    async def update_project(self) -> Any:
        payload = await request.json(default={})
        if not isinstance(payload, dict):
            return error_response("请求体必须是 JSON 对象", status_code=400)
        try:
            return json_response(
                {"project": self.store.update_project(payload.get("id"), payload.get("name"))}
            )
        except FileNotFoundError:
            return error_response("项目不存在", status_code=404)
        except CanvasValidationError as exc:
            return error_response(str(exc), status_code=400)

    async def delete_project(self) -> Any:
        payload = await request.json(default={})
        if not isinstance(payload, dict):
            return error_response("请求体必须是 JSON 对象", status_code=400)
        try:
            self.store.delete_project(payload.get("id"))
            return json_response({"deleted": True})
        except FileNotFoundError:
            return error_response("项目不存在", status_code=404)
        except CanvasValidationError as exc:
            return error_response(str(exc), status_code=400)

    async def list_canvases(self) -> Any:
        include_deleted = str(request.query.get("deleted", "") or "").lower() in {"1", "true"}
        try:
            return json_response({"canvases": self.store.list_canvases(include_deleted)})
        except CanvasValidationError as exc:
            return error_response(str(exc), status_code=500)

    async def create_canvas(self) -> Any:
        payload = await request.json(default={})
        if not isinstance(payload, dict):
            return error_response("请求体必须是 JSON 对象", status_code=400)
        try:
            return json_response({"canvas": self.store.create_canvas(payload)})
        except FileNotFoundError:
            return error_response("项目不存在", status_code=404)
        except CanvasValidationError as exc:
            return error_response(str(exc), status_code=400)

    async def update_canvas(self) -> Any:
        payload = await request.json(default={})
        try:
            return json_response({"canvas": self.store.update_canvas(payload)})
        except FileNotFoundError:
            return error_response("画布或项目不存在", status_code=404)
        except CanvasValidationError as exc:
            return error_response(str(exc), status_code=400)

    async def delete_canvas(self) -> Any:
        return await self._canvas_state_action("delete")

    async def restore_canvas(self) -> Any:
        return await self._canvas_state_action("restore")

    async def purge_canvas(self) -> Any:
        return await self._canvas_state_action("purge")

    async def _canvas_state_action(self, action: str) -> Any:
        payload = await request.json(default={})
        if not isinstance(payload, dict):
            return error_response("请求体必须是 JSON 对象", status_code=400)
        try:
            canvas_id = payload.get("id")
            if action == "delete":
                self.store.trash_canvas(canvas_id)
            elif action == "restore":
                self.store.restore_canvas(canvas_id)
            else:
                self.store.purge_canvas(canvas_id)
            return json_response({"ok": True})
        except FileNotFoundError:
            return error_response("画布不存在", status_code=404)
        except CanvasValidationError as exc:
            return error_response(str(exc), status_code=400)

    async def get_library(self) -> Any:
        return json_response(self.store.list_library())

    async def add_library_image(self) -> Any:
        payload = await request.json(default={})
        if not isinstance(payload, dict):
            return error_response("请求体必须是 JSON 对象", status_code=400)
        try:
            asset_id = str(payload.get("assetId") or "")
            asset_payload = self.store.asset_payload(asset_id)
            asset_path, _ = self.store.get_asset(asset_id)
            with PILImage.open(asset_path) as image:
                width, height = image.size
                image_format = str(image.format or "").lower().replace("jpeg", "jpg")
            entry = self.store.add_image_to_library(
                {"id": asset_id, "width": width, "height": height, "format": image_format},
                payload.get("name"),
                payload.get("source"),
                payload.get("prompt"),
                payload.get("tags"),
                payload.get("ratio"),
                payload.get("artist"),
            )
            return json_response({"image": entry, **asset_payload})
        except FileNotFoundError:
            return error_response("图片资源不存在", status_code=404)
        except CanvasValidationError as exc:
            return error_response(str(exc), status_code=400)

    async def delete_library_image(self) -> Any:
        payload = await request.json(default={})
        if not isinstance(payload, dict):
            return error_response("请求体必须是 JSON 对象", status_code=400)
        try:
            self.store.remove_image_from_library(payload.get("id"))
            return json_response({"deleted": True})
        except CanvasValidationError as exc:
            return error_response(str(exc), status_code=400)

    async def save_library_prompt(self) -> Any:
        payload = await request.json(default={})
        if not isinstance(payload, dict):
            return error_response("请求体必须是 JSON 对象", status_code=400)
        try:
            return json_response({"prompt": self.store.save_prompt_asset(payload)})
        except CanvasValidationError as exc:
            return error_response(str(exc), status_code=400)

    async def delete_library_prompt(self) -> Any:
        payload = await request.json(default={})
        if not isinstance(payload, dict):
            return error_response("请求体必须是 JSON 对象", status_code=400)
        try:
            self.store.delete_prompt_asset(payload.get("id"))
            return json_response({"deleted": True})
        except CanvasValidationError as exc:
            return error_response(str(exc), status_code=400)

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
        keep_character = bool(payload.get("keepCharacter", False))
        character_name = _short_text(payload.get("characterName"), 120).strip()

        try:
            if self.retag_callback is None:
                raise ValueError("画布图片反推服务不可用")

            asset_path, _ = self.store.get_asset(asset_id)
            result = await self.retag_callback(
                str(asset_path),
                user_hint,
                keep_character,
                character_name if keep_character else "",
            )
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
        canvas_id = str(request.query.get("id", "") or "") or None
        try:
            return json_response(self.store.load_workspace(canvas_id))
        except FileNotFoundError:
            return error_response("画布不存在", status_code=404)
        except CanvasValidationError as exc:
            return error_response(str(exc), status_code=500)

    async def save_workspace(self) -> Any:
        payload = await request.json(default={})
        if not isinstance(payload, dict):
            return error_response("请求体必须是 JSON 对象", status_code=400)
        try:
            canvas_id = str(payload.get("canvasId") or "") or None
            workspace = self.store.save_workspace(payload, canvas_id)
            return json_response({"saved": True, "updatedAt": workspace["updatedAt"]})
        except FileNotFoundError:
            return error_response("画布不存在", status_code=404)
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

    async def download_asset(self) -> Any:
        asset_id = str(request.query.get("id", "") or "")
        try:
            asset_path, mime_type = self.store.get_asset(asset_id)
            return file_response(
                asset_path,
                filename=f"bestnai-{asset_id}{asset_path.suffix.lower()}",
                content_type=mime_type,
            )
        except FileNotFoundError:
            return error_response("图片资源不存在", status_code=404)
        except CanvasValidationError as exc:
            return error_response(str(exc), status_code=400)

    async def export_workspace(self) -> Any:
        canvas_id = str(request.query.get("id", "") or "") or None
        try:
            workspace_path = self.store._workspace_file(canvas_id)
            if not workspace_path.exists():
                self.store.save_workspace(self.store.empty_workspace(), canvas_id)
        except FileNotFoundError:
            return error_response("画布不存在", status_code=404)
        except CanvasValidationError as exc:
            return error_response(str(exc), status_code=400)

        return file_response(
            workspace_path,
            filename="bestnai-canvas.json",
            content_type="application/json",
        )

    async def import_workspace(self) -> Any:
        canvas_id = str(request.query.get("id", "") or "") or None
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
            workspace = self.store.save_workspace(payload, canvas_id)
            return json_response(workspace)
        except FileNotFoundError:
            return error_response("画布不存在", status_code=404)
        except (UnicodeDecodeError, json.JSONDecodeError):
            return error_response("文件不是有效的 JSON", status_code=400)
        except CanvasValidationError as exc:
            return error_response(str(exc), status_code=400)
        except Exception as exc:
            logger.exception(f"[BestNAI/Canvas] 导入工作区失败: {exc}")
            return error_response("导入工作区失败", status_code=500)
