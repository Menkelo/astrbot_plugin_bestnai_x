from __future__ import annotations

import sys
import types
import unittest
from pathlib import Path


workspace_dir = Path(__file__).resolve().parents[2]
if str(workspace_dir) not in sys.path:
    sys.path.insert(0, str(workspace_dir))

sys.modules.setdefault("aiohttp", types.ModuleType("aiohttp"))

from astrbot_plugin_bestnai_x.services.image_ratio import (
    RATIO_SOURCE_ARTIST,
    RATIO_SOURCE_DEFAULT,
    RATIO_SOURCE_IMAGE,
    RATIO_SOURCE_USER,
    choose_ratio_source,
)


ROOT = Path(__file__).resolve().parents[1]


class ChooseRatioSourceTest(unittest.TestCase):
    def test_user_written_ratio_always_wins(self) -> None:
        for artist in (True, False):
            for inferred in (True, False):
                with self.subTest(artist=artist, inferred=inferred):
                    self.assertEqual(
                        choose_ratio_source(True, artist, inferred),
                        RATIO_SOURCE_USER,
                    )

    def test_artist_ratio_beats_image_inference(self) -> None:
        # 这条是本次修复的核心：反推推断出的比例不得盖掉画师串里的比例
        self.assertEqual(
            choose_ratio_source(False, True, True),
            RATIO_SOURCE_ARTIST,
        )

    def test_artist_ratio_used_when_no_image_inference(self) -> None:
        self.assertEqual(
            choose_ratio_source(False, True, False),
            RATIO_SOURCE_ARTIST,
        )

    def test_image_inference_used_only_when_nothing_else_specifies(self) -> None:
        self.assertEqual(
            choose_ratio_source(False, False, True),
            RATIO_SOURCE_IMAGE,
        )

    def test_default_when_nothing_specifies(self) -> None:
        self.assertEqual(
            choose_ratio_source(False, False, False),
            RATIO_SOURCE_DEFAULT,
        )

    def test_precedence_is_strictly_ordered(self) -> None:
        rank = {
            RATIO_SOURCE_USER: 0,
            RATIO_SOURCE_ARTIST: 1,
            RATIO_SOURCE_IMAGE: 2,
            RATIO_SOURCE_DEFAULT: 3,
        }
        # 把 8 种组合全枚举一遍，确认永远选中排名最高的那个可用来源
        for user in (True, False):
            for artist in (True, False):
                for inferred in (True, False):
                    available = [RATIO_SOURCE_DEFAULT]
                    if inferred:
                        available.append(RATIO_SOURCE_IMAGE)
                    if artist:
                        available.append(RATIO_SOURCE_ARTIST)
                    if user:
                        available.append(RATIO_SOURCE_USER)
                    expected = min(available, key=lambda s: rank[s])
                    with self.subTest(user=user, artist=artist, inferred=inferred):
                        self.assertEqual(
                            choose_ratio_source(user, artist, inferred),
                            expected,
                        )


class RetagRatioWiringTest(unittest.TestCase):
    """反推推断的比例必须以参数传递，不能拼进提示词字符串。"""

    def setUp(self) -> None:
        self.main = (ROOT / "main.py").read_text(encoding="utf-8")

    def test_inferred_ratio_is_not_appended_to_the_prompt(self) -> None:
        # 拼进提示词会让它在 prompt_has_explicit_ratio 判定里等同于用户手写，
        # 从而把画师串的比例挤掉
        self.assertNotIn('merged_prompt = f"{merged_prompt} {inferred_ratio}"', self.main)

    def test_inferred_ratio_is_passed_as_fallback(self) -> None:
        self.assertIn("fallback_ratio: str = \"\"", self.main)
        self.assertIn("fallback_ratio=inferred_ratio", self.main)

    def test_precedence_helper_is_used(self) -> None:
        self.assertIn("ratio_source = choose_ratio_source(", self.main)
        self.assertIn("user_specified=user_specified_ratio", self.main)
        self.assertIn("artist_has_ratio=artist_has_ratio", self.main)
        self.assertIn("has_inferred_ratio=bool(fallback_ratio)", self.main)


if __name__ == "__main__":
    unittest.main()


class CanvasGenerationSettingsWiringTest(unittest.TestCase):
    """步数 / 引导系数 / 种子的前后端接线。"""

    def setUp(self) -> None:
        self.main = (ROOT / "main.py").read_text(encoding="utf-8")
        self.editor = (ROOT / "pages" / "canvas" / "canvas.js").read_text(encoding="utf-8")
        self.html = (ROOT / "pages" / "canvas" / "editor.html").read_text(encoding="utf-8")
        self.store = (ROOT / "services" / "canvas.py").read_text(encoding="utf-8")

    def test_backend_clamps_steps_and_scale(self) -> None:
        self.assertIn("def _clamp_steps", self.main)
        self.assertIn("def _clamp_scale", self.main)
        self.assertIn("MIN_STEPS", self.main)
        self.assertIn("MAX_SCALE", self.main)
        # 画布传来的值不可信，必须夹在合法区间内
        self.assertIn("steps=self._clamp_steps(payload.get(\"steps\")", self.main)
        self.assertIn("scale=self._clamp_scale(payload.get(\"scale\")", self.main)

    def test_seed_is_returned_and_reusable(self) -> None:
        self.assertIn('seed=payload.get("seed")', self.main)
        self.assertIn('"seed": result.seed', self.main)
        self.assertIn("state.generation.steps", self.editor)
        self.assertIn("seed: node.meta?.retagSeed || undefined", self.editor)

    def test_settings_panel_exists_and_is_global(self) -> None:
        self.assertIn('id="genSettingsPanel"', self.html)
        self.assertIn('id="genStepsInput"', self.html)
        self.assertIn('id="genScaleInput"', self.html)
        self.assertIn("function setupGenSettings", self.editor)
        self.assertIn("function clampGenValue", self.editor)

    def test_new_meta_fields_are_persisted(self) -> None:
        # 工作区不保存这些字段的话，刷新页面种子就丢了
        for field in ("retagSeed", "retagFromMetadata", '"seed"', '"steps"', '"scale"'):
            with self.subTest(field=field):
                self.assertIn(field, self.store)
        for key in ("steps", "scale"):
            with self.subTest(preference=key):
                self.assertIn(f'"{key}"', self.store)

    def test_image_card_shows_seed_instead_of_prompt(self) -> None:
        card = self.editor.split("meta.className = \"image-meta\"", 1)[1].split(
            "meta.append(title, detail)", 1
        )[0]
        self.assertIn("seed", card)
        self.assertNotIn("node.meta?.prompt", card)
