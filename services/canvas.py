from __future__ import annotations

import asyncio
import base64
import inspect
import json
import math
import re
import threading
import time
from datetime import datetime, timezone
from io import BytesIO
from pathlib import Path
from typing import Any, Awaitable, Callable, Dict, List, Set, Tuple
from uuid import uuid4

from PIL import Image as PILImage

from astrbot.api import logger
from astrbot.api.web import error_response, file_response, json_response, request

try:  # Support both plugin-package imports and the legacy top-level test import.
    from ..constants import normalize_nai_seed
except ImportError:  # pragma: no cover - exercised by standalone ``services`` imports
    from constants import normalize_nai_seed

try:
    from .nai_metadata import read_image_generation_info
except ImportError:  # pragma: no cover - legacy flat layout
    from nai_metadata import read_image_generation_info
from .runtime_state import get_astrbot_plugin_data_dir


GenerateCallback = Callable[
    [Dict[str, Any]],
    Awaitable[Tuple[List[Tuple[str, bytes]], Dict[str, Any]]],
]
ConfigCallback = Callable[[], Dict[str, Any]]
TagTranslationCallback = Callable[[str], Awaitable[Dict[str, Any]]]
# The current callback accepts ``(path, hint, debug, source_seed, source_prompt)``.
# Keep this open-ended so older plugin hosts with the former three-argument
# callback can still register the canvas service during a hot reload.
RetagCallback = Callable[..., Awaitable[Dict[str, Any]]]

MAX_NODES = 160
MAX_CONNECTIONS = 320
MAX_WORKSPACE_BYTES = 2 * 1024 * 1024
MAX_UPLOAD_BYTES = 15 * 1024 * 1024
MAX_IMAGE_PIXELS = 30_000_000

# Debug traces are user-facing diagnostics, not arbitrary workspace data.  Keep
# a bounded, JSON-safe subset when a workspace is persisted so a malformed
# client payload cannot make saves enormous (or inject fields that the canvas
# renderer never expects).
MAX_DEBUG_STAGES = 32
MAX_DEBUG_NOTES = 64
MAX_DEBUG_RUNS = 8
MAX_DEBUG_DEPTH = 4
MAX_DEBUG_KEY_LENGTH = 120
MAX_DEBUG_VALUE_LENGTH = 2000

RETAG_LAYER_CATEGORIES = (
    "identity",
    "subject",
    "expression",
    "hair",
    "eyes",
    "skin",
    "traits",
    "accessory",
    "clothing",
    "legwear",
    "footwear",
    "handwear",
    "pose",
    "gaze",
    "gesture",
    "composition",
    "background",
    "atmosphere",
    "lighting",
    "style",
    "other",
)
RETAG_LAYER_MODES = frozenset({"auto", "preserve", "drop"})
MAX_RETAG_TAGS_PER_GROUP = 64
MAX_RETAG_TAGS_TOTAL = 320
MAX_RETAG_TAG_LENGTH = 160
MAX_RETAG_TAG_TRANSLATIONS = 320
MAX_RETAG_TAG_TRANSLATION_LENGTH = 160

# 刚生成、还没被放进节点的图片不能马上回收，
# 否则前端拿到 assetId 却还没保存工作区时会被误删。
ASSET_GC_GRACE_SECONDS = 3600

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


def _sanitize_retag_tag_groups(value: Any) -> Dict[str, List[str]]:
    if not isinstance(value, dict):
        return {}

    groups: Dict[str, List[str]] = {}
    total = 0
    seen: Set[str] = set()
    for category in RETAG_LAYER_CATEGORIES:
        raw_tags = value.get(category)
        if not isinstance(raw_tags, list):
            continue
        tags: List[str] = []
        for raw_tag in raw_tags:
            if total >= MAX_RETAG_TAGS_TOTAL or len(tags) >= MAX_RETAG_TAGS_PER_GROUP:
                break
            tag = _short_text(raw_tag, MAX_RETAG_TAG_LENGTH).strip(" ,;\n\t")
            key = tag.casefold()
            if not tag or key in seen:
                continue
            seen.add(key)
            tags.append(tag)
            total += 1
        if tags:
            groups[category] = tags
        if total >= MAX_RETAG_TAGS_TOTAL:
            break
    return groups


def _sanitize_retag_layer_modes(value: Any) -> Dict[str, str]:
    if not isinstance(value, dict):
        return {}
    result: Dict[str, str] = {}
    for category in RETAG_LAYER_CATEGORIES:
        mode = str(value.get(category) or "").strip().casefold()
        if mode in RETAG_LAYER_MODES:
            result[category] = mode
    return result


MAX_CHAR_PROMPTS_STORED = 16
MAX_CHAR_PROMPT_LENGTH = 2000
_CHAR_POSITION_RE = re.compile(r"^[A-E][1-5]$")


def _sanitize_char_prompts(value: Any) -> List[Dict[str, str]]:
    """工作区里缓存的多角色参数，边界与 core/char_prompts 保持一致。"""
    if not isinstance(value, list):
        return []
    result: List[Dict[str, str]] = []
    for raw_entry in value[:MAX_CHAR_PROMPTS_STORED]:
        if not isinstance(raw_entry, dict):
            continue
        prompt = _short_text(raw_entry.get("prompt"), MAX_CHAR_PROMPT_LENGTH).strip()
        if not prompt:
            continue
        entry = {
            "prompt": prompt,
            "negative_prompt": _short_text(
                raw_entry.get("negative_prompt"),
                MAX_CHAR_PROMPT_LENGTH,
            ).strip(),
            "position": "",
        }
        position = str(raw_entry.get("position") or "").strip().upper()
        if _CHAR_POSITION_RE.fullmatch(position):
            entry["position"] = position
        result.append(entry)
    return result


def _sanitize_retag_tag_translations(value: Any) -> Dict[str, str]:
    if not isinstance(value, dict):
        return {}
    result: Dict[str, str] = {}
    for raw_key, raw_name in value.items():
        if len(result) >= MAX_RETAG_TAG_TRANSLATIONS:
            break
        key = re.sub(
            r"[\s_]+",
            "_",
            _short_text(raw_key, MAX_RETAG_TAG_LENGTH).strip().casefold(),
        ).strip("_")
        name = _short_text(
            raw_name,
            MAX_RETAG_TAG_TRANSLATION_LENGTH,
        ).strip(" ,;，；\n\t")
        if key and name:
            result[key] = name
    return result


def _sanitize_debug_value(value: Any, depth: int = 0) -> Any:
    """Return a small JSON-safe representation of a debug note value."""
    if value is None or isinstance(value, bool):
        return value
    if isinstance(value, int):
        # Python integers are unbounded; cap them to a sensible JSON number so
        # a hostile payload cannot create a huge decimal string.
        return max(-1_000_000_000_000, min(1_000_000_000_000, value))
    if isinstance(value, float):
        return value if math.isfinite(value) else 0

    if depth >= MAX_DEBUG_DEPTH:
        return _short_text(value, MAX_DEBUG_VALUE_LENGTH)

    if isinstance(value, dict):
        result: Dict[str, Any] = {}
        for index, (key, item) in enumerate(value.items()):
            if index >= MAX_DEBUG_NOTES:
                break
            result[_short_text(key, MAX_DEBUG_KEY_LENGTH)] = _sanitize_debug_value(item, depth + 1)
        return result

    if isinstance(value, (list, tuple)):
        return [
            _sanitize_debug_value(item, depth + 1)
            for item in list(value)[:MAX_DEBUG_NOTES]
        ]

    return _short_text(value, MAX_DEBUG_VALUE_LENGTH)


def _sanitize_debug_trace(value: Any) -> Dict[str, Any] | None:
    """Keep the stable DebugTrace shape while dropping untrusted extras."""
    if not isinstance(value, dict):
        return None

    stages: List[Dict[str, Any]] = []
    raw_stages = value.get("stages", [])
    if isinstance(raw_stages, list):
        for raw_stage in raw_stages[:MAX_DEBUG_STAGES]:
            if not isinstance(raw_stage, dict):
                continue
            stage = {
                "name": _short_text(raw_stage.get("name"), MAX_DEBUG_KEY_LENGTH),
                "ms": int(_bounded_number(raw_stage.get("ms"), 0, 0, 86_400_000)),
            }
            if raw_stage.get("error") not in (None, ""):
                stage["error"] = _short_text(raw_stage.get("error"), MAX_DEBUG_VALUE_LENGTH)
            stages.append(stage)

    notes: Dict[str, Any] = {}
    raw_notes = value.get("notes", {})
    if isinstance(raw_notes, dict):
        for index, (key, item) in enumerate(raw_notes.items()):
            if index >= MAX_DEBUG_NOTES:
                break
            notes[_short_text(key, MAX_DEBUG_KEY_LENGTH)] = _sanitize_debug_value(item)

    return {
        "scope": _short_text(value.get("scope"), MAX_DEBUG_KEY_LENGTH),
        "totalMs": int(_bounded_number(value.get("totalMs"), 0, 0, 86_400_000)),
        "stages": stages,
        "notes": notes,
    }


def _sanitize_debug_payload(value: Any) -> Dict[str, Any] | None:
    """Sanitize one trace or the frontend's collection of named traces.

    The canvas keeps the retag and generate traces together as
    ``meta.debug = {retag: {...}, generate: {...}}``.  Older workspaces (and
    a few third-party clients) may still send a single trace directly.  The
    previous sanitizer treated the collection as a trace and silently dropped
    both named runs when the workspace was re-opened, which made the debug bar
    appear empty after a save/load round-trip.
    """
    if not isinstance(value, dict):
        return None

    # Backward-compatible flat trace shape.
    if any(key in value for key in ("scope", "totalMs", "stages", "notes")):
        trace = _sanitize_debug_trace(value)
        return trace

    runs: Dict[str, Any] = {}
    for index, (key, raw_trace) in enumerate(value.items()):
        if index >= MAX_DEBUG_RUNS:
            break
        name = _short_text(key, MAX_DEBUG_KEY_LENGTH).strip()
        if not name or not re.fullmatch(r"[A-Za-z0-9_-]{1,64}", name):
            continue
        trace = _sanitize_debug_trace(raw_trace)
        if trace is not None:
            runs[name] = trace

    return runs or None


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
        # 这些 JSON 全是「读-改-写」，用一把可重入锁把整段操作圈起来。
        # 单线程事件循环下本就不会交错，但资源回收要跨多个文件读写，
        # 万一 web 层跑在线程池里就会丢更新。
        self._lock = threading.RLock()
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
                {
                    "lastCanvasId": "",
                    "ratio": "",
                    "artist": "",
                    "model": "",
                    "advSteps": 0,
                    "advScale": 0,
                    "advCfgRescale": 0,
                    "advVariety": False,
                },
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
            "model": _short_text(payload.get("model"), 64),
            "advSteps": int(_bounded_number(payload.get("advSteps"), 0, 0, 200)),
            "advScale": _bounded_number(payload.get("advScale"), 0, 0, 100),
            "advCfgRescale": _bounded_number(payload.get("advCfgRescale"), 0, 0, 1),
            "advVariety": bool(payload.get("advVariety", False)),
        }

    def save_preferences(self, payload: Any) -> Dict[str, str]:
        with self._lock:
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
            if "model" in payload:
                current["model"] = _short_text(payload.get("model"), 64)
            if "advSteps" in payload:
                current["advSteps"] = int(_bounded_number(payload.get("advSteps"), 0, 0, 200))
            if "advScale" in payload:
                current["advScale"] = _bounded_number(payload.get("advScale"), 0, 0, 100)
            if "advCfgRescale" in payload:
                current["advCfgRescale"] = _bounded_number(payload.get("advCfgRescale"), 0, 0, 1)
            if "advVariety" in payload:
                current["advVariety"] = bool(payload.get("advVariety", False))
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
        with self._lock:
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
        with self._lock:
            project_id = self._validate_entity_id(project_id, "项目")
            projects = self._projects()
            project = next((item for item in projects if item.get("id") == project_id), None)
            if project is None:
                raise FileNotFoundError(project_id)
            project["name"] = _short_text(name, 60).strip() or project.get("name") or "未命名项目"
            self._write_json(self.projects_path, {"projects": projects})
            return dict(project)

    def delete_project(self, project_id: Any) -> None:
        with self._lock:
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
        with self._lock:
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
        with self._lock:
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
        with self._lock:
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

        with self._lock:
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

        self.collect_orphan_assets()

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

            meta = {
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
                "translationCharacter": _short_text(raw_meta.get("translationCharacter"), 240),
                "translationSeries": _short_text(raw_meta.get("translationSeries"), 240),
                "retagBasePrompt": _short_text(raw_meta.get("retagBasePrompt"), 6000),
                "retagPrompt": _short_text(raw_meta.get("retagPrompt"), 6000),
                "retagCharacter": _short_text(raw_meta.get("retagCharacter"), 240),
                "retagSeries": _short_text(raw_meta.get("retagSeries"), 240),
                "retagAssetId": _short_text(raw_meta.get("retagAssetId"), 128),
                "retagRatio": _short_text(raw_meta.get("retagRatio"), 32),
                "retagSeed": normalize_nai_seed(raw_meta.get("retagSeed")) or 0,
                "retagSeedPrompt": _short_text(raw_meta.get("retagSeedPrompt"), 6000),
                "retagSeedRatio": _short_text(raw_meta.get("retagSeedRatio"), 32),
                "retagSeedArtist": _short_text(raw_meta.get("retagSeedArtist"), 120),
                "retagSeedRaw": bool(raw_meta.get("retagSeedRaw", False)),
                "retagFromMetadata": bool(raw_meta.get("retagFromMetadata", False)),
                "retagFromCanvasCache": bool(raw_meta.get("retagFromCanvasCache", False)),
                "retagLayerExpanded": bool(raw_meta.get("retagLayerExpanded", False)),
                "seed": normalize_nai_seed(raw_meta.get("seed")) or 0,
                "retagged": bool(raw_meta.get("retagged", False)),
                "userResized": bool(raw_meta.get("userResized", False)),
                # 用户手动选过画幅后，首次链接图片的自动对齐不再生效
                "ratioManual": bool(raw_meta.get("ratioManual", False)),
                # 命中内嵌参数时沿用的原图采样参数（0/空 = 未命中）
                "retagSteps": int(_bounded_number(raw_meta.get("retagSteps"), 0, 0, 200)),
                "retagScale": _bounded_number(raw_meta.get("retagScale"), 0, 0, 100),
                "retagCfgRescale": _bounded_number(
                    raw_meta.get("retagCfgRescale"), 0, 0, 100
                ),
                "retagNoiseSchedule": _short_text(raw_meta.get("retagNoiseSchedule"), 32),
                # 节点高级参数：steps/scale/cfgRescale 仅在设置过时落盘
                # （见下方循环），缺省物化成 0 会被前端当成"手写值 0"
                "varietyBoost": bool(raw_meta.get("varietyBoost", False)),
                "advParamsExpanded": bool(raw_meta.get("advParamsExpanded", False)),
                # 单次生成张数（1-4），>1 时前端按两列网格排布
                "count": int(_bounded_number(raw_meta.get("count"), 1, 1, 4)),
            }
            for _key, _bound in (
                ("steps", (0, 0, 200)),
                ("scale", (0, 0, 100)),
                ("cfgRescale", (0, 0, 1)),
            ):
                _raw_value = raw_meta.get(_key)
                if _raw_value not in (None, ""):
                    meta[_key] = _bounded_number(_raw_value, *_bound)
            debug = _sanitize_debug_payload(raw_meta.get("debug"))
            if debug is not None:
                meta["debug"] = debug
            retag_tag_groups = _sanitize_retag_tag_groups(raw_meta.get("retagTagGroups"))
            if retag_tag_groups:
                meta["retagTagGroups"] = retag_tag_groups
            tag_translations = _sanitize_retag_tag_translations(raw_meta.get("tagTranslations"))
            if tag_translations:
                meta["tagTranslations"] = tag_translations
            retag_tag_translations = _sanitize_retag_tag_translations(
                raw_meta.get("retagTagTranslations")
            )
            if retag_tag_translations:
                meta["retagTagTranslations"] = retag_tag_translations
            retag_layer_modes = _sanitize_retag_layer_modes(raw_meta.get("retagLayerModes"))
            if retag_layer_modes:
                meta["retagLayerModes"] = retag_layer_modes
            # V4+ 多角色参数：结构化透传给生图网关的分区生成
            char_prompts = _sanitize_char_prompts(raw_meta.get("retagCharPrompts"))
            if char_prompts:
                meta["retagCharPrompts"] = char_prompts
                meta["retagUseCoords"] = bool(raw_meta.get("retagUseCoords", False))

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
                # 节点级生图模型（4.5/V5），生成时再校验合法性
                "model": _short_text(raw_node.get("model"), 64),
                "raw": bool(raw_node.get("raw", False)),
                "assetId": asset_id,
                "createdAt": _short_text(raw_node.get("createdAt"), 64),
                "meta": meta,
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

        node_count_dropped = False

        with self._lock:
            workspace_path = self._workspace_file(canvas_id)
            temp_path = workspace_path.with_suffix(".json.tmp")
            temp_path.write_bytes(encoded)
            temp_path.replace(workspace_path)
            if canvas_id is not None:
                canvases = self._canvases()
                canvas = next((item for item in canvases if item.get("id") == canvas_id), None)
                if canvas is not None:
                    previous_count = int(canvas.get("nodeCount", 0) or 0)
                    canvas["nodeCount"] = len(workspace["nodes"])
                    canvas["updatedAt"] = workspace["updatedAt"]
                    node_count_dropped = canvas["nodeCount"] < previous_count
                    self._write_json(self.canvases_path, {"canvases": canvases})

        # 只在确实删掉节点时才扫一遍，避免每次自动保存都遍历所有工作区
        if node_count_dropped:
            self.collect_orphan_assets()

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
            "images": [dict(item) for item in library["images"]],
            "prompts": [dict(item) for item in library["prompts"]],
        }

    def _referenced_asset_ids(self) -> Set[str] | None:
        """收集所有还在被引用的图片资源 ID。

        任何一个工作区读不出来就返回 None，宁可不回收也不能误删在用的图。
        """
        referenced: Set[str] = set()

        try:
            for entry in self._library()["images"]:
                asset_id = str(entry.get("id") or "")
                if asset_id:
                    referenced.add(asset_id)
        except Exception as exc:
            logger.warning(f"[BestNAI/Canvas] 读取素材库失败，跳过资源回收: {exc}")
            return None

        workspace_files = list(self.workspaces_dir.glob("*.json"))

        if self.workspace_path.exists():
            workspace_files.append(self.workspace_path)

        for path in workspace_files:
            try:
                payload = json.loads(path.read_text(encoding="utf-8"))
            except Exception as exc:
                logger.warning(
                    f"[BestNAI/Canvas] 工作区 {path.name} 读取失败，跳过资源回收: {exc}"
                )
                return None

            nodes = payload.get("nodes", []) if isinstance(payload, dict) else []

            if not isinstance(nodes, list):
                continue

            for node in nodes:
                if not isinstance(node, dict):
                    continue

                asset_id = str(node.get("assetId") or "")
                if asset_id:
                    referenced.add(asset_id)

                meta = node.get("meta")

                if isinstance(meta, dict):
                    # 反推节点会记住原图，同样算引用
                    retag_asset_id = str(meta.get("retagAssetId") or "")
                    if retag_asset_id:
                        referenced.add(retag_asset_id)

        return referenced

    def collect_orphan_assets(self) -> int:
        """删除不再被任何画布节点或素材库引用的图片文件，返回删除数量。"""
        with self._lock:
            referenced = self._referenced_asset_ids()

            if referenced is None:
                return 0

            now = time.time()
            removed = 0

            for path in self.assets_dir.iterdir():
                if not path.is_file():
                    continue

                asset_id = path.stem

                # 不是本插件命名规则的文件一律不动
                if not ASSET_ID_RE.fullmatch(asset_id):
                    continue

                if asset_id in referenced:
                    continue

                try:
                    if now - path.stat().st_mtime < ASSET_GC_GRACE_SECONDS:
                        continue

                    path.unlink()
                    removed += 1
                except OSError as exc:
                    logger.warning(f"[BestNAI/Canvas] 删除资源 {path.name} 失败: {exc}")

            if removed:
                logger.info(f"[BestNAI/Canvas] 已回收 {removed} 个未引用的图片资源")

            return removed

    def add_image_to_library(
        self,
        asset: Dict[str, Any],
        name: Any = "",
        source: Any = "",
        prompt: Any = "",
        tags: Any = "",
        ratio: Any = "",
        artist: Any = "",
        seed: Any = 0,
        tag_translations: Any = None,
    ) -> Dict[str, Any]:
        with self._lock:
            asset_id = str(asset.get("id") or "")
            if not ASSET_ID_RE.fullmatch(asset_id):
                raise CanvasValidationError("图片资源 ID 无效")
            library = self._library()
            existing = next((item for item in library["images"] if item.get("id") == asset_id), None)
            entry = existing or {"id": asset_id, "createdAt": self._timestamp()}
            incoming_seed = normalize_nai_seed(seed) or 0
            previous_seed = normalize_nai_seed(entry.get("seed")) or 0
            translations = _sanitize_retag_tag_translations(tag_translations)
            if not translations:
                translations = _sanitize_retag_tag_translations(
                    entry.get("tagTranslations")
                )

            def _keep_text(value: Any, key: str, limit: int) -> str:
                incoming = _short_text(value, limit).strip()
                return incoming or _short_text(entry.get(key), limit).strip()

            entry.update(
                {
                    "name": _keep_text(name, "name", 160) or f"图片 {asset_id[:8]}",
                    "width": int(_bounded_number(asset.get("width"), entry.get("width", 0), 0, 20_000)),
                    "height": int(_bounded_number(asset.get("height"), entry.get("height", 0), 0, 20_000)),
                    "format": _keep_text(asset.get("format"), "format", 16),
                    "source": _keep_text(source, "source", 80),
                    "prompt": _keep_text(prompt, "prompt", 6000),
                    "tags": _keep_text(tags, "tags", 6000),
                    "artist": _keep_text(artist, "artist", 120),
                    "ratio": _keep_text(ratio, "ratio", 32),
                    # Zero is the canvas sentinel for “no known NovelAI seed”.
                    # Never let a later save erase a valid seed already stored
                    # for the same asset.
                    "seed": incoming_seed or previous_seed,
                }
            )
            if translations:
                entry["tagTranslations"] = translations
            if existing is None:
                library["images"].insert(0, entry)
            self._write_json(self.library_path, library)
            return dict(entry)

    def remove_image_from_library(self, asset_id: Any) -> None:
        asset_id = str(asset_id or "")
        if not ASSET_ID_RE.fullmatch(asset_id):
            raise CanvasValidationError("图片资源 ID 无效")

        with self._lock:
            library = self._library()
            library["images"] = [item for item in library["images"] if item.get("id") != asset_id]
            self._write_json(self.library_path, library)

        self.collect_orphan_assets()

    def repair_library_image_seed(self, asset_id: Any) -> Dict[str, Any]:
        """旧版本收录的素材可能没存 seed；从图片内嵌的生成元数据补一次。

        支持 NovelAI PNG（tEXt 块）与 JPEG/WebP（EXIF UserComment），
        以及 SD WebUI 的 parameters 格式；图片被重新编码且元数据丢失时
        保持原样返回，绝不臆造种子。已有合法种子的条目原样返回。
        """
        asset_id = str(asset_id or "")
        if not ASSET_ID_RE.fullmatch(asset_id):
            raise CanvasValidationError("图片资源 ID 无效")

        with self._lock:
            library = self._library()
            entry = next(
                (item for item in library["images"] if item.get("id") == asset_id),
                None,
            )
            if entry is None:
                raise CanvasValidationError("素材不在图片库中")
            if normalize_nai_seed(entry.get("seed")):
                return dict(entry)

            asset_path, _ = self.get_asset(asset_id)
            info = read_image_generation_info(str(asset_path))
            recovered = normalize_nai_seed(info.get("seed"))
            if not recovered:
                return dict(entry)

            entry["seed"] = recovered
            self._write_json(self.library_path, library)
            return dict(entry)

    def save_prompt_asset(self, payload: Any) -> Dict[str, Any]:
        with self._lock:
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
        with self._lock:
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
        tag_translation_callback: TagTranslationCallback | None = None,
        data_dir: Path | None = None,
    ) -> None:
        self.plugin_name = plugin_name
        self.generate_callback = generate_callback
        self.config_callback = config_callback
        self.retag_callback = retag_callback
        self.tag_translation_callback = tag_translation_callback
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
            ("tags/translate", self.translate_tags, ["POST"], "Infinite Canvas：读取中英文 Tags"),
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
            ("library/image/recover", self.recover_library_image, ["POST"], "Infinite Canvas：回填图片种子"),
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
                payload.get("seed"),
                tag_translations=payload.get("tagTranslations"),
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

    async def recover_library_image(self) -> Any:
        payload = await request.json(default={})
        if not isinstance(payload, dict):
            return error_response("请求体必须是 JSON 对象", status_code=400)
        try:
            entry = await asyncio.to_thread(
                self.store.repair_library_image_seed,
                payload.get("id"),
            )
            return json_response({"image": entry})
        except FileNotFoundError:
            return error_response("图片资源不存在", status_code=404)
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

    async def translate_tags(self) -> Any:
        payload = await request.json(default={})
        if not isinstance(payload, dict):
            return error_response("请求体必须是 JSON 对象", status_code=400)

        tags = _short_text(payload.get("tags"), 6000).strip()
        if not tags or self.tag_translation_callback is None:
            return json_response({"pairs": [], "translations": {}})

        try:
            result = await self.tag_translation_callback(tags)
            raw_pairs = result.get("pairs") if isinstance(result, dict) else []
            pairs: List[Dict[str, str]] = []
            if isinstance(raw_pairs, list):
                for item in raw_pairs[:MAX_RETAG_TAG_TRANSLATIONS]:
                    if not isinstance(item, dict):
                        continue
                    tag = _short_text(item.get("tag"), MAX_RETAG_TAG_LENGTH).strip()
                    cn_name = _short_text(
                        item.get("cnName"),
                        MAX_RETAG_TAG_TRANSLATION_LENGTH,
                    ).strip(" ,;，；\n\t")
                    if tag:
                        pairs.append({"tag": tag, "cnName": cn_name})
            translations = _sanitize_retag_tag_translations(
                result.get("translations") if isinstance(result, dict) else {}
            )
            return json_response({"pairs": pairs, "translations": translations})
        except ValueError as exc:
            return error_response(str(exc), status_code=422)
        except Exception as exc:
            logger.warning(f"[BestNAI/Canvas] Tags 中英对照读取失败: {exc}")
            return error_response("中文 Tags 读取失败", status_code=502)

    async def retag(self) -> Any:
        payload = await request.json(default={})
        if not isinstance(payload, dict):
            return error_response("请求体必须是 JSON 对象", status_code=400)

        asset_id = str(payload.get("assetId") or "")
        user_hint = _short_text(payload.get("userHint"), 6000).strip()
        source_seed = normalize_nai_seed(payload.get("seed"))
        source_prompt = _short_text(payload.get("sourcePrompt"), 6000).strip()

        try:
            if self.retag_callback is None:
                raise ValueError("画布图片反推服务不可用")

            asset_path, _ = self.store.get_asset(asset_id)
            debug = bool(payload.get("debug", False))
            callback = self.retag_callback
            try:
                parameters = list(inspect.signature(callback).parameters.values())
                positional = [
                    item
                    for item in parameters
                    if item.kind in (
                        inspect.Parameter.POSITIONAL_ONLY,
                        inspect.Parameter.POSITIONAL_OR_KEYWORD,
                    )
                ]
                has_varargs = any(
                    item.kind is inspect.Parameter.VAR_POSITIONAL
                    for item in parameters
                )
            except (TypeError, ValueError):
                positional = []
                has_varargs = True

            # Older canvas hosts used
            # ``(path, hint, keep_character, character_name)``. Keep that
            # callback shape working while the current callback receives the
            # optional cached seed and prompt after the debug flag.
            legacy_identity_callback = (
                len(positional) >= 4
                and positional[2].name in {"keep_character", "character_name"}
            )
            if legacy_identity_callback:
                callback_args = [str(asset_path), user_hint, False, ""]
            else:
                callback_args = [str(asset_path), user_hint]
                if has_varargs or len(positional) >= 3:
                    callback_args.append(debug)
                if has_varargs or len(positional) >= 4:
                    callback_args.append(source_seed)
                if has_varargs or len(positional) >= 5:
                    callback_args.append(source_prompt)
            result = await callback(*callback_args)
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
