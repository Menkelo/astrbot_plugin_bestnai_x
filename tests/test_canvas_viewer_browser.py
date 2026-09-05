"""Browser regressions for the viewer. Optional: pip install playwright && playwright install chromium.

All bridge calls use local fixtures; these tests never contact a generation provider.
"""
from __future__ import annotations

import base64
import copy
import mimetypes
import os
import unittest
from io import BytesIO
from pathlib import Path
from urllib.parse import urlparse

from PIL import Image, ImageDraw

try:
    from playwright.sync_api import sync_playwright, expect
except ImportError:
    sync_playwright = None


PAGE_ROOT = Path(__file__).resolve().parents[1] / "pages" / "canvas"
RAW_TAGS = "best quality, artist:example, 1.3::blue hair, smile ::,\n1girl, outdoors, {sunlight}"
PARAMS = {
    "model": "nai-diffusion-4-5-full", "steps": 28, "scale": 6.5,
    "sampler": "k_euler_ancestral", "cfgRescale": 0, "noiseSchedule": "karras",
    "varietyBoost": True, "quality": False, "ucPreset": "0", "imageFormat": "png",
    "negativePrompt": "lowres, blurry", "characterUseCoords": True, "characterUseOrder": True,
    "characterPrompts": [
        {"prompt": "blue hair, smile", "negative_prompt": "closed eyes", "center": {"x": .17, "y": .53}},
        {"prompt": "red hair, hat", "negative_prompt": "glasses", "position": "D3"},
    ],
}
BRIDGE = """
window.AstrBotPluginPage = {
  ready: async () => {},
  apiGet: async (path, payload = {}) => {
    if (path === 'canvas/asset/params' && window.metadataDelay) {
      await new Promise(resolve => setTimeout(resolve, window.metadataDelay));
    }
    return window.fixtureRequest('GET', path, payload);
  },
  apiPost: async (path, payload = {}) => {
    if (path === 'canvas/tags/translate' && window.translationDelay) {
      await new Promise(resolve => setTimeout(resolve, window.translationDelay));
    }
    return window.fixtureRequest('POST', path, payload);
  },
  download: async () => {},
};
"""


@unittest.skipIf(sync_playwright is None, "optional Playwright is not installed")
class CanvasViewerBrowserTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.playwright = sync_playwright().start()
        if not Path(cls.playwright.chromium.executable_path).exists():
            cls.playwright.stop()
            raise unittest.SkipTest("optional Playwright Chromium is not installed")
        cls.browser = cls.playwright.chromium.launch(headless=True)
        output = BytesIO()
        image = Image.new("RGB", (960, 640), "#e0e7ff")
        draw = ImageDraw.Draw(image)
        draw.ellipse((600, 50, 850, 300), fill="#fbbf24")
        draw.polygon([(0, 640), (360, 220), (730, 640)], fill="#818cf8")
        draw.polygon([(300, 640), (750, 300), (960, 640)], fill="#4338ca")
        image.save(output, "PNG")
        cls.data_url = "data:image/png;base64," + base64.b64encode(output.getvalue()).decode()

    @classmethod
    def tearDownClass(cls):
        cls.browser.close()
        cls.playwright.stop()

    def setUp(self):
        self.context = self.browser.new_context(
            viewport={"width": 1440, "height": 900}, permissions=["clipboard-read", "clipboard-write"],
        )
        self.page = self.context.new_page()
        self.page.set_default_timeout(5000)
        self.errors = []
        self.calls = []
        self.saved_images = []
        self.workspace = {
            "viewport": {"x": 0, "y": 0, "scale": 1}, "connections": [],
            "nodes": [self.node("a", 80, RAW_TAGS), self.node("b", 490, "landscape, forest")],
        }
        self.library = [{
            "id": "b" * 32, "name": "Library B", "width": 960, "height": 640,
            "seed": 222, "tags": "landscape, forest", "dataUrl": self.data_url,
            "generationMeta": {"sampler": "k_euler", "steps": 20, "negativePrompt": "fog"},
        }]
        self.page.on("pageerror", lambda error: self.errors.append(str(error)))
        self.page.expose_function("fixtureRequest", self.request)
        self.page.route("**/*", self.serve)
        self.page.goto("http://localhost:9355/editor.html")
        expect(self.page.locator(".image-preview-wrap")).to_have_count(2)

    def tearDown(self):
        self.context.close()
        self.assertEqual(self.errors, [])
        self.assertFalse(any(path == "canvas/retag" for _, path, _ in self.calls))

    def node(self, letter, x, tags):
        return {
            "id": "image_" + letter, "type": "image", "x": x, "y": 145, "width": 320,
            "title": "Image " + letter.upper(), "assetId": letter * 32, "dataUrl": self.data_url,
            "meta": {"width": 960, "height": 640, "tags": tags, "seed": 111 if letter == "a" else 222},
        }

    def serve(self, route):
        path = urlparse(route.request.url).path
        if path == "/api/plugin/page/bridge-sdk.js":
            route.fulfill(body=BRIDGE, content_type="text/javascript")
            return
        file = (PAGE_ROOT / path.lstrip("/")).resolve()
        if file.is_relative_to(PAGE_ROOT) and file.is_file():
            route.fulfill(body=file.read_bytes(), content_type=mimetypes.guess_type(file)[0] or "text/plain")
        else:
            route.fulfill(status=404)

    def request(self, method, path, payload):
        self.calls.append((method, path, copy.deepcopy(payload)))
        if path == "canvas/config":
            return {"plugin": {"name": "NAI Diffusion X", "version": "test"}}
        if path == "canvas/canvases":
            return {"canvases": [{"id": "default", "title": "Viewer test", "projectId": "default"}]}
        if path == "canvas/workspace":
            if method == "POST":
                self.workspace = copy.deepcopy(payload)
            return copy.deepcopy(self.workspace)
        if path == "canvas/library":
            return {"images": copy.deepcopy(self.library), "prompts": []}
        if path == "canvas/asset":
            return {"dataUrl": self.data_url}
        if path == "canvas/asset/params":
            return copy.deepcopy(PARAMS) if payload["id"] == "a" * 32 else {
                "sampler": "k_euler", "steps": 20, "negativePrompt": "fog",
            }
        if path == "canvas/tags/translate":
            # An incomplete translation response must not remove the other English tags.
            return {"pairs": [{"tag": "blue hair", "cnName": "蓝发"}], "translations": {"blue_hair": "蓝发"}}
        if path == "canvas/library/image/add":
            self.saved_images.append(copy.deepcopy(payload))
            image = {**payload, "id": payload["assetId"], "width": 960, "height": 640}
            self.library.insert(0, image)
            return {"image": image}
        return {}

    def open_image(self):
        self.page.locator('[data-node-id="image_a"] .image-preview-wrap').press("Enter")
        expect(self.page.locator("#imageViewerNote")).to_contain_text("Variety+: 开启")

    def screenshot(self, name):
        directory = os.environ.get("BESTNAI_VIEWER_SCREENSHOTS")
        if directory:
            target = Path(directory)
            target.mkdir(parents=True, exist_ok=True)
            self.page.screenshot(path=str(target / name))

    def test_raw_and_filtered_tags_keep_source_text_and_copy_individual_tags(self):
        self.open_image()
        self.assertEqual(self.page.locator("#imageViewerTags").text_content(), RAW_TAGS)
        self.page.locator("#imageViewerFilterToggle").check()
        chips = self.page.locator("#imageViewerTags .image-viewer-tag-chip")
        expect(chips).to_have_count(5)
        expect(chips.first).to_have_text("blue hair / 蓝发")
        chips.first.click()
        self.assertEqual(self.page.evaluate("navigator.clipboard.readText()"), "blue hair")
        self.assertIn("1.3::blue hair, smile ::", self.page.locator("#imageViewerTags").get_attribute("data-copy-text"))
        self.screenshot("viewer-desktop-filtered.png")
        self.page.locator("#imageViewerFilterToggle").uncheck()
        self.assertEqual(self.page.locator("#imageViewerTags").text_content(), RAW_TAGS)

    def test_mouse_selection_and_copy_work_for_all_text_surfaces(self):
        self.open_image()
        for selector in ("#imageViewerTags", "#imageViewerNegative", "#imageViewerNote", "#imageViewerCharacter0Tags", "#imageViewerCharacter0Negative"):
            with self.subTest(selector=selector):
                target = self.page.locator(selector)
                target.scroll_into_view_if_needed()
                box = target.bounding_box()
                self.page.mouse.move(box["x"] + 12, box["y"] + 17)
                self.page.mouse.down()
                self.page.mouse.move(box["x"] + 115, box["y"] + 17, steps=10)
                self.page.mouse.up()
                selected = self.page.evaluate("window.getSelection().toString()")
                self.assertTrue(selected.strip(), selector)
                self.page.keyboard.press("Control+c")
                self.assertEqual(self.page.evaluate("navigator.clipboard.readText()"), selected)
        self.screenshot("viewer-desktop-parameters.png")

    def test_copy_all_uses_recovered_negative_characters_and_advanced_params(self):
        self.open_image()
        self.page.locator("#imageViewerCopyAllBtn").click()
        copied = self.page.evaluate("navigator.clipboard.readText()").replace("\r\n", "\n")
        for text in (RAW_TAGS, "Negative prompt: lowres, blurry", "角色 1", "0.17, 0.53", "closed eyes", "red hair, hat", "CFG rescale: 0", "Noise schedule: karras", "UC preset: 0", "Quality: 关闭"):
            self.assertIn(text, copied)

    def test_library_action_places_image_and_canvas_action_saves_all_params(self):
        self.open_image()
        expect(self.page.locator("#imageViewerPlaceBtn")).to_be_hidden()
        self.page.locator("#imageViewerSaveBtn").click()
        expect(self.page.locator("#imageViewerSaveBtn")).to_have_text("已收藏")
        self.assertEqual(len(self.saved_images), 1)
        self.assertEqual(self.saved_images[0]["generationMeta"]["characterPrompts"][0]["negative_prompt"], "closed eyes")
        self.page.keyboard.press("Escape")
        self.page.locator("#assetLibraryBtn").click()
        stacks = self.page.locator(".asset-stack-card")
        if stacks.count():
            stacks.first.click()
        self.page.locator(".asset-image-card").first.click()
        expect(self.page.locator("#imageViewerPlaceBtn")).to_be_visible()
        expect(self.page.locator("#imageViewerRetagBtn")).to_be_hidden()
        expect(self.page.locator("#imageViewerSaveBtn")).to_be_disabled()
        self.page.locator("#imageViewerPlaceBtn").click()
        expect(self.page.locator("#imageViewer")).to_be_hidden()
        expect(self.page.locator(".image-preview-wrap")).to_have_count(3)
        self.page.locator(".image-preview-wrap").last.press("Enter")
        expect(self.page.locator("#imageViewerNote")).to_contain_text("Noise schedule: karras")

    def test_late_translations_do_not_replace_raw_view_or_another_image(self):
        self.open_image()
        self.page.evaluate("window.translationDelay = 200")
        self.page.locator("#imageViewerFilterToggle").check()
        self.page.locator("#imageViewerFilterToggle").uncheck()
        self.page.wait_for_timeout(300)
        self.assertEqual(self.page.locator("#imageViewerTags").text_content(), RAW_TAGS)
        self.page.locator("#imageViewerNextBtn").click()
        expect(self.page.locator("#imageViewerTags")).to_have_text("landscape, forest")
        expect(self.page.locator("#imageViewerNegative")).to_have_text("fog")
        expect(self.page.locator("#imageViewerCharactersSection")).to_be_hidden()

    def test_responsive_rail_stays_separate_from_image(self):
        self.open_image()
        for width, height in ((1440, 900), (1024, 768), (760, 900), (700, 800), (620, 780), (390, 844)):
            with self.subTest(viewport=(width, height)):
                self.page.set_viewport_size({"width": width, "height": height})
                self.page.wait_for_timeout(350)
                image = self.page.locator("#imageViewerImage").bounding_box()
                rail = self.page.locator("#imageViewerDetails").bounding_box()
                self.assertGreater(rail["width"], 200)
                if width > 760:
                    self.assertLessEqual(image["x"] + image["width"], rail["x"] - 16)
                    self.assertAlmostEqual(rail["height"], height - 36, delta=2)
                else:
                    self.assertLessEqual(image["y"] + image["height"], rail["y"] - 8)
                    self.assertAlmostEqual(rail["height"], height * .45, delta=2)
                self.assertLessEqual(rail["x"] + rail["width"], width)
                self.assertLessEqual(rail["y"] + rail["height"], height)
                next_button = self.page.locator("#imageViewerNextBtn").bounding_box()
                fold_button = self.page.locator("#imageViewerFoldBtn").bounding_box()
                self.assertTrue(
                    fold_button["y"] + fold_button["height"] < next_button["y"]
                    or fold_button["x"] > next_button["x"] + next_button["width"]
                )
        self.screenshot("viewer-mobile.png")


if __name__ == "__main__":
    unittest.main()
