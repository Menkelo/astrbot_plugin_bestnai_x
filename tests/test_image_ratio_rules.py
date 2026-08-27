from __future__ import annotations

import sys
import unittest
from pathlib import Path


workspace_dir = Path(__file__).resolve().parents[2]
if str(workspace_dir) not in sys.path:
    sys.path.insert(0, str(workspace_dir))

from astrbot_plugin_bestnai_x.services.image_ratio import (  # noqa: E402
    MAX_TOTAL_PIXELS,
    clamp_to_pixel_budget,
    format_aspect_ratio,
    snap_dim,
)


class SnapDimTest(unittest.TestCase):
    def test_rounds_to_the_nearest_multiple_of_64(self) -> None:
        self.assertEqual(snap_dim(832), 832)
        self.assertEqual(snap_dim(900), 896)
        self.assertEqual(snap_dim(929), 960)

    def test_never_goes_below_64(self) -> None:
        self.assertEqual(snap_dim(1), 64)
        self.assertEqual(snap_dim(0), 64)
        self.assertEqual(snap_dim(-100), 64)


class ClampToPixelBudgetTest(unittest.TestCase):
    def test_valid_size_is_untouched(self) -> None:
        self.assertEqual(clamp_to_pixel_budget(832, 1216), (832, 1216))

    def test_unaligned_size_only_snaps(self) -> None:
        # 900x1200 = 1,080,000，在预算内，只需要 64 对齐
        self.assertEqual(clamp_to_pixel_budget(900, 1200), (896, 1216))

    def test_oversized_input_keeps_its_aspect_ratio(self) -> None:
        # 以前会被换成某个预设，比例说改就改
        width, height = clamp_to_pixel_budget(2048, 3072)

        self.assertLessEqual(width * height, MAX_TOTAL_PIXELS)
        self.assertAlmostEqual(width / height, 2048 / 3072, delta=0.05)

    def test_result_is_always_valid(self) -> None:
        for source in ((4000, 4000), (3072, 1024), (100, 5000), (1, 1), (777, 999)):
            with self.subTest(source=source):
                width, height = clamp_to_pixel_budget(*source)

                self.assertEqual(width % 64, 0)
                self.assertEqual(height % 64, 0)
                self.assertGreaterEqual(width, 64)
                self.assertGreaterEqual(height, 64)
                self.assertLessEqual(width * height, MAX_TOTAL_PIXELS)

    def test_square_oversize_scales_both_sides(self) -> None:
        width, height = clamp_to_pixel_budget(2048, 2048)

        self.assertEqual(width, height)
        self.assertLessEqual(width * height, MAX_TOTAL_PIXELS)


class FormatAspectRatioTest(unittest.TestCase):
    def test_common_sizes_reduce_to_simplest_terms(self) -> None:
        self.assertEqual(format_aspect_ratio(832, 1216), "13:19")
        self.assertEqual(format_aspect_ratio(1024, 1024), "1:1")
        self.assertEqual(format_aspect_ratio(1216, 832), "19:13")

    def test_awkward_ratio_degrades_to_decimal(self) -> None:
        self.assertEqual(format_aspect_ratio(1000, 999), "1.00:1")

    def test_invalid_size(self) -> None:
        self.assertEqual(format_aspect_ratio(0, 100), "—")
        self.assertEqual(format_aspect_ratio(100, -1), "—")


if __name__ == "__main__":
    unittest.main()
