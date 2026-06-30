from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Dict

from astrbot.api import logger


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

            with open(self.state_path, "w", encoding="utf-8") as f:
                json.dump(self.state, f, ensure_ascii=False, indent=2)

            return True

        except Exception as e:
            logger.error(f"[BestNAI] 保存运行状态失败: {e}")
            return False

    def get_default_artist_slot(self) -> str:
        value = self.state.get("default_artist_slot", "")

        if isinstance(value, str):
            return value.strip()

        return ""

    def set_default_artist_slot(self, slot_name: str) -> bool:
        slot_name = str(slot_name or "").strip()

        if not slot_name:
            return False

        self.state["default_artist_slot"] = slot_name

        return self.save()

    def clear_default_artist_slot(self) -> bool:
        if "default_artist_slot" in self.state:
            del self.state["default_artist_slot"]

        return self.save()
