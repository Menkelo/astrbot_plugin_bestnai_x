from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Dict, Iterable

from astrbot.api import logger


# 旧版本把默认画师预设存成全局的一个字符串，任何人切换都会影响所有会话。
# 现在按会话存，这个键只作为迁移期的只读兜底，不再写入。
LEGACY_GLOBAL_KEY = "default_artist_slot"
SESSION_MAP_KEY = "artist_slot_by_session"


def get_astrbot_plugin_data_dir(plugin_name: str) -> Path:
    current = Path(__file__).resolve()

    for parent in current.parents:
        if parent.name == "data":
            return parent / "plugin_data" / plugin_name

    return Path.cwd() / "data" / "plugin_data" / plugin_name


class RuntimeStateService:
    def __init__(self, plugin_name: str) -> None:
        self.plugin_name = plugin_name
        self.plugin_data_dir = get_astrbot_plugin_data_dir(plugin_name)
        self.plugin_data_dir.mkdir(parents=True, exist_ok=True)

        self.state_path = self.plugin_data_dir / "runtime_state.json"
        self.state: Dict[str, Any] = {}

        self.load()

    def load(self) -> None:
        self.state = {}

        try:
            if self.state_path.exists():
                with open(self.state_path, "r", encoding="utf-8") as f:
                    data = json.load(f)

                if isinstance(data, dict):
                    self.state = data

        except Exception as e:
            logger.warning(f"[BestNAI] 读取运行状态失败: {e}")
            self.state = {}

    def save(self) -> bool:
        try:
            self.plugin_data_dir.mkdir(parents=True, exist_ok=True)

            # 先写临时文件再替换，避免写到一半崩溃留下半截 JSON
            temp_path = self.state_path.with_suffix(".json.tmp")
            temp_path.write_text(
                json.dumps(self.state, ensure_ascii=False, indent=2),
                encoding="utf-8",
            )
            temp_path.replace(self.state_path)

            return True

        except Exception as e:
            logger.error(f"[BestNAI] 保存运行状态失败: {e}")
            return False

    def _session_map(self) -> Dict[str, str]:
        raw = self.state.get(SESSION_MAP_KEY)

        if not isinstance(raw, dict):
            return {}

        return {
            str(k): str(v).strip()
            for k, v in raw.items()
            if isinstance(k, str) and isinstance(v, str) and k.strip() and v.strip()
        }

    def _legacy_global_slot(self) -> str:
        value = self.state.get(LEGACY_GLOBAL_KEY, "")

        if isinstance(value, str):
            return value.strip()

        return ""

    def get_artist_slot(self, session_id: str) -> str:
        """取某个会话的默认画师预设。

        会话自己没设过时，回落到旧版本留下的全局值（如果有），
        再没有就返回空，由上层用配置里的默认预设。
        """
        session_id = str(session_id or "").strip()

        if session_id:
            slot = self._session_map().get(session_id, "")

            if slot:
                return slot

        return self._legacy_global_slot()

    def set_artist_slot(self, session_id: str, slot_name: str) -> bool:
        session_id = str(session_id or "").strip()
        slot_name = str(slot_name or "").strip()

        if not session_id or not slot_name:
            return False

        session_map = self._session_map()
        session_map[session_id] = slot_name
        self.state[SESSION_MAP_KEY] = session_map

        return self.save()

    def clear_artist_slot(self, session_id: str) -> bool:
        session_id = str(session_id or "").strip()

        if not session_id:
            return False

        session_map = self._session_map()
        session_map.pop(session_id, None)
        self.state[SESSION_MAP_KEY] = session_map

        # 该会话回到配置默认，就不该再被旧的全局值拉回去
        if self._legacy_global_slot():
            self.state.pop(LEGACY_GLOBAL_KEY, None)
            logger.info("[BestNAI] 已清除旧版本遗留的全局默认画师预设")

        return self.save()

    def prune_artist_slots(self, valid_slot_names: Iterable[str]) -> int:
        """删掉指向已不存在的画师预设的记录，返回删除条数。"""
        valid = {str(name).strip() for name in valid_slot_names if str(name).strip()}

        session_map = self._session_map()
        stale = [sid for sid, slot in session_map.items() if slot not in valid]

        for sid in stale:
            session_map.pop(sid, None)

        legacy = self._legacy_global_slot()
        legacy_stale = bool(legacy) and legacy not in valid

        if legacy_stale:
            self.state.pop(LEGACY_GLOBAL_KEY, None)

        if not stale and not legacy_stale:
            return 0

        self.state[SESSION_MAP_KEY] = session_map
        self.save()

        return len(stale) + (1 if legacy_stale else 0)
