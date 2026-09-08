"""Browser regressions for the viewer. Optional: pip install playwright && playwright install chromium.

All bridge calls use local fixtures; these tests never contact a generation provider.
"""
from __future__ import annotations

import base64
import copy
import mimetypes
import os
import json
import unittest
import zipfile
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
    if (path === 'canvas/asset' && window.assetDelays?.[payload.id]) {
      await new Promise(resolve => setTimeout(resolve, window.assetDelays[payload.id]));
    }
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
  download: async (path, payload, filename) => {
    window.downloads = [...(window.downloads || []), {path, payload, filename}];
    return window.fixtureRequest('DOWNLOAD', path, {...payload, filename});
  },
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
        self.original_assets = {}
        self.generation_error = None
        self.workspace = {
            "viewport": {"x": 0, "y": 0, "scale": 1}, "connections": [],
            "nodes": [self.node("a", 80, RAW_TAGS), self.node("b", 490, "landscape, forest")],
        }
        self.library = [{
            "id": "b" * 32, "name": "Library B", "width": 960, "height": 640,
            "seed": 222, "tags": "landscape, forest",
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
            return {"configured": True, "plugin": {"name": "NAI Diffusion X", "version": "test"}}
        if path == "canvas/canvases":
            return {"canvases": [{"id": "default", "title": "Viewer test", "projectId": "default"}]}
        if path == "canvas/workspace":
            if method == "POST":
                self.workspace = copy.deepcopy(payload)
            return copy.deepcopy(self.workspace)
        if path == "canvas/library":
            return {"images": copy.deepcopy(self.library), "prompts": []}
        if path in ("canvas/asset", "canvas/asset/thumbnail"):
            if path == "canvas/asset" and not payload.get("preview") and payload["id"] in self.original_assets:
                return copy.deepcopy(self.original_assets[payload["id"]])
            return {"dataUrl": self.data_url}
        if path == "canvas/generate":
            if self.generation_error:
                raise RuntimeError(self.generation_error)
            meta = {
                **copy.deepcopy(PARAMS), "finalPrompt": payload["prompt"], "translatedPrompt": payload["prompt"],
                "seed": payload.get("seed") or 123, "model": payload["model"],
                "negativePrompt": payload.get("negative_prompt", "default negative"),
                "cfgRescale": payload.get("cfg_rescale", 0), "characterPrompts": payload.get("retagCharPrompts", []),
            }
            return {"assets": [{"id": "d" * 32, "width": 960, "height": 640, "dataUrl": self.data_url}], "meta": meta}
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
        self.page.locator('[data-node-id="image_a"] .image-preview-wrap').click()
        expect(self.page.locator("#imageViewerNote")).to_contain_text("Variety+: 开启")
        expect(self.page.locator("#imageViewerRetagBtn")).to_have_count(0)

    def open_role_editor(self):
        self.workspace = {
            "viewport": {"x": 0, "y": 0, "scale": 1}, "connections": [],
            "nodes": [{
                "id": "prompt_roles", "type": "prompt", "x": 140, "y": 650,
                "width": 320, "height": 430, "title": "角色编辑", "prompt": "outdoors", "ratio": "2:3",
                "meta": {"retagCharacterExpanded": True, "retagCharPrompts": copy.deepcopy(PARAMS["characterPrompts"])},
            }, {
                "id": "note_other", "type": "note", "x": 980, "y": 160,
                "width": 260, "height": 190, "title": "另一个节点", "note": "测试置顶时保留第一次点击",
            }],
        }
        self.page.reload()
        expect(self.page.locator(".retag-character-card.open")).to_be_visible()
        expect(self.page.get_by_role("textbox", name="角色 1正面提示词")).to_be_visible()

    def assert_disjoint(self, first, second):
        self.assertTrue(
            first["x"] + first["width"] <= second["x"]
            or second["x"] + second["width"] <= first["x"]
            or first["y"] + first["height"] <= second["y"]
            or second["y"] + second["height"] <= first["y"],
            (first, second),
        )

    def open_node_panels(self, *, y=300, height=430, scale=1, viewport_y=0, meta=None):
        self.workspace = {
            "viewport": {"x": 0, "y": viewport_y, "scale": scale}, "connections": [],
            "nodes": [{
                "id": "prompt_panels", "type": "prompt", "x": 160, "y": y,
                "width": 400, "height": height, "title": "面板回归", "prompt": "outdoors",
                "meta": {
                    "retagLayerExpanded": True,
                    "retagTagGroups": {
                        category: [f"{category} tag {index}" for index in range(16)]
                        for category in ("subject", "hair", "clothing", "pose", "background")
                    },
                    **(meta or {}),
                },
            }],
        }
        self.page.reload()
        body = self.page.locator(".node-attach-stack > .retag-layer-card:not(.adv-card) > .retag-layer-body")
        expect(body).to_be_visible()
        self.page.wait_for_timeout(80)
        self.assertAlmostEqual(
            self.page.locator("#world").evaluate("element => new DOMMatrixReadOnly(getComputedStyle(element).transform).a"),
            scale,
            delta=.001,
        )
        return body

    def pan_canvas(self, delta_y):
        self.page.mouse.move(1200, 700)
        self.page.mouse.down(button="middle")
        self.page.mouse.move(1200, 700 + delta_y, steps=8)
        self.page.mouse.up(button="middle")
        self.page.wait_for_timeout(100)

    def test_tag_panel_keeps_height_when_panning(self):
        body = self.open_node_panels()
        initial = body.bounding_box()
        self.assertAlmostEqual(initial["height"], 620, delta=1)
        self.pan_canvas(-480)
        panned = body.bounding_box()
        self.assertAlmostEqual(panned["y"], initial["y"] - 480, delta=1)
        self.assertAlmostEqual(panned["height"], initial["height"], delta=1)
        self.assertGreater(body.evaluate("element => element.scrollHeight - element.clientHeight"), 100)
        transform = self.page.locator("#world").get_attribute("style")
        self.page.mouse.move(panned["x"] + panned["width"] / 2, panned["y"] + 100)
        self.page.mouse.wheel(0, 180)
        self.page.wait_for_timeout(120)
        self.assertGreater(body.evaluate("element => element.scrollTop"), 0)
        self.assertEqual(self.page.locator("#world").get_attribute("style"), transform)

    def test_tag_panel_keeps_height_limit_at_different_canvas_scales(self):
        for scale in (.65, 1, 1.75):
            with self.subTest(scale=scale):
                body = self.open_node_panels(scale=scale, viewport_y=300 - 831 * scale)
                box = body.bounding_box()
                self.assertAlmostEqual(box["height"], 620 * scale, delta=1)

    def test_tag_height_stays_fixed_during_node_drag_resize_and_sibling_fold(self):
        body = self.open_node_panels(y=100, height=560)
        initial_height = body.bounding_box()["height"]
        header = self.page.locator(".node-head").bounding_box()
        self.page.mouse.move(header["x"] + 120, header["y"] + 12)
        self.page.mouse.down()
        self.page.mouse.move(header["x"] + 120, header["y"] - 188, steps=6)
        self.page.mouse.up()
        self.page.wait_for_timeout(80)
        dragged_height = body.bounding_box()["height"]
        self.assertAlmostEqual(dragged_height, initial_height, delta=1)
        handle = self.page.locator(".node-resize-handle").bounding_box()
        self.page.mouse.move(handle["x"] + 8, handle["y"] + 8)
        self.page.mouse.down()
        self.page.mouse.move(handle["x"] + 8, handle["y"] - 122, steps=6)
        self.page.mouse.up()
        self.page.wait_for_timeout(80)
        resized_height = body.bounding_box()["height"]
        self.assertAlmostEqual(resized_height, initial_height, delta=1)
        # A further shrink must stop at the same minimum the browser displays.
        handle = self.page.locator(".node-resize-handle").bounding_box()
        self.page.mouse.move(handle["x"] + 8, handle["y"] + 8)
        self.page.mouse.down()
        self.page.mouse.move(handle["x"] + 8, handle["y"] - 72, steps=4)
        self.page.mouse.up()
        self.assertEqual(
            self.page.locator(".prompt-node").evaluate("element => parseFloat(element.style.height)"),
            self.page.locator(".prompt-node").bounding_box()["height"],
        )
        self.page.locator(".adv-card > .retag-layer-toggle").click()
        self.page.wait_for_timeout(80)
        self.assertAlmostEqual(body.bounding_box()["height"], initial_height, delta=1)
        self.page.locator(".adv-card > .retag-layer-toggle").click()
        self.page.wait_for_timeout(80)
        self.assertAlmostEqual(body.bounding_box()["height"], resized_height, delta=2)

    def test_plain_advanced_panel_does_not_overlap_tags_after_resize(self):
        self.open_node_panels(meta={"advParamsExpanded": True, "retagSteps": 28, "retagScale": 7})
        self.page.set_viewport_size({"width": 1400, "height": 760})
        self.page.wait_for_timeout(100)
        advanced = self.page.locator(".adv-card > .retag-layer-body")
        self.assertEqual(advanced.evaluate("element => getComputedStyle(element).maxHeight"), "none")
        self.assertLessEqual(advanced.evaluate("element => element.scrollHeight - element.clientHeight"), 1)

    def test_tag_panel_keeps_height_after_recorder_expansion_and_window_resize(self):
        body = self.open_node_panels(y=-260)
        original_height = body.bounding_box()["height"]
        self.page.locator("#debugBarToggle").click()
        self.page.wait_for_timeout(150)
        self.assertAlmostEqual(body.bounding_box()["height"], original_height, delta=1)
        self.page.locator("#debugBarToggle").click()
        self.page.wait_for_timeout(100)
        self.assertAlmostEqual(body.bounding_box()["height"], original_height, delta=2)
        self.page.set_viewport_size({"width": 1400, "height": 640})
        self.page.wait_for_timeout(100)
        self.assertAlmostEqual(body.bounding_box()["height"], original_height, delta=1)

    def test_reused_parameters_scroll_before_zoom_and_reach_the_last_field(self):
        self.open_node_panels(y=120, meta={
            "advParamsExpanded": True, "generationSeed": 123, "negativePrompt": "lowres, blurry",
            "retagSampler": "custom_sampler_" * 24, "noiseSchedule": "custom_noise_schedule_" * 20,
        })
        body = self.page.locator(".adv-card > .retag-layer-body")
        self.assertLessEqual(body.evaluate("element => element.scrollWidth - element.clientWidth"), 1)
        body.evaluate("element => element.scrollLeft = 1000")
        self.assertEqual(body.evaluate("element => element.scrollLeft"), 0)
        self.assertGreater(body.evaluate("element => element.scrollHeight - element.clientHeight"), 30)
        transform = self.page.locator("#world").get_attribute("style")
        box = body.bounding_box()
        self.page.mouse.move(box["x"] + box["width"] / 2, box["y"] + 8)
        self.page.mouse.wheel(0, 180)
        self.page.wait_for_timeout(120)
        self.assertGreater(body.evaluate("element => element.scrollTop"), 0)
        self.assertEqual(self.page.locator("#world").get_attribute("style"), transform)
        seed = self.page.get_by_role("textbox", name="生成种子")
        negative = self.page.get_by_role("textbox", name="节点负面提示词")
        seed.fill("222")
        negative.fill("soft focus")
        for field in (seed, negative):
            field.scroll_into_view_if_needed()
            frame, box = body.bounding_box(), field.bounding_box()
            self.assertGreaterEqual(box["x"], frame["x"])
            self.assertLessEqual(box["x"] + box["width"], frame["x"] + frame["width"])
            self.assertGreaterEqual(box["y"], frame["y"])
            self.assertLessEqual(box["y"] + box["height"], frame["y"] + frame["height"])
            self.assertEqual(body.evaluate("element => element.scrollLeft"), 0)
        expect(seed).to_have_value("222")
        expect(negative).to_have_value("soft focus")
        self.assertEqual(self.page.locator("#world").get_attribute("style"), transform)

    def test_upward_character_panel_keeps_height_after_zoom(self):
        self.open_role_editor()
        original_height = self.page.locator(".retag-character-body").bounding_box()["height"]
        self.workspace["viewport"] = {"x": -100, "y": -380, "scale": 1.5}
        self.page.reload()
        self.page.wait_for_timeout(100)
        body = self.page.locator(".retag-character-body").bounding_box()
        self.assertAlmostEqual(body["height"], original_height * 1.5, delta=1)
        self.page.set_viewport_size({"width": 1400, "height": 640})
        self.page.wait_for_timeout(100)
        self.assertAlmostEqual(
            self.page.locator(".retag-character-body").bounding_box()["height"],
            original_height * 1.5,
            delta=1,
        )

    def test_character_editor_scrolls_without_zooming_the_canvas(self):
        self.open_role_editor()
        self.page.get_by_role("textbox", name="角色 1正面提示词").evaluate("element => element.style.height = '700px'")
        self.page.wait_for_timeout(100)
        editor = self.page.locator(".retag-character-editor-popover")
        self.assertGreater(editor.evaluate("element => element.scrollHeight - element.clientHeight"), 100)
        box = editor.bounding_box()
        self.assertLessEqual(box["y"] + box["height"], self.page.locator("#debugBar").bounding_box()["y"] - 8)
        transform = self.page.locator("#world").get_attribute("style")
        head = self.page.locator(".retag-character-row.is-active .retag-character-row-head").bounding_box()
        self.page.mouse.move(head["x"] + head["width"] / 2, head["y"] + 5)
        self.page.mouse.wheel(0, 160)
        self.page.wait_for_timeout(120)
        self.assertGreater(editor.evaluate("element => element.scrollTop"), 0)
        self.assertEqual(self.page.locator("#world").get_attribute("style"), transform)

    def test_node_redraw_preserves_other_panel_scroll_positions(self):
        body = self.open_node_panels(y=20)
        body.evaluate("element => element.scrollTop = 200")
        previous = body.evaluate("element => element.scrollTop")
        self.assertGreater(previous, 100)
        self.page.locator(".retag-character-add").evaluate("element => element.click()")
        self.page.wait_for_timeout(100)
        self.assertAlmostEqual(body.evaluate("element => element.scrollTop"), previous, delta=1)

    def test_tag_removal_and_restore_reach_cached_generation_in_both_modes(self):
        character = "ganyu_(genshin_impact)"
        source = f"1.3::{character}, rolua, nuegochi ::, yoneyama_mai, 0.7::sixii"
        for raw in (False, True):
            with self.subTest(raw=raw):
                self.page.goto("about:blank")
                self.workspace = {
                    "viewport": {"x": 0, "y": 0, "scale": 1},
                    "connections": [{"source": "image_a", "target": "prompt_tags"}],
                    "nodes": [self.node("a", 80, source), {
                        "id": "prompt_tags", "type": "prompt", "x": 500, "y": 90,
                        "width": 400, "height": 430, "title": "移除标签", "prompt": "outdoors", "raw": raw,
                        "meta": {
                            "retagAssetId": "a" * 32, "retagSeed": 111, "retagFromMetadata": True,
                            "retagPrompt": source, "retagRawPrompt": source, "retagLayerExpanded": True,
                            "retagTagGroups": {"other": [character, "rolua", "nuegochi", "yoneyama_mai", "0.7::sixii"]},
                            "retagTagTranslations": {character: "甘雨（原神）"},
                        },
                    }],
                }
                self.page.goto("http://localhost:9355/editor.html")
                chip = self.page.locator(".retag-layer-tag").filter(has_text=character)
                expect(chip).to_have_attribute("aria-pressed", "false")
                chip.click()
                expect(chip).to_have_attribute("aria-pressed", "true")
                self.page.locator(".generate-btn").click()
                expect(self.page.locator(".image-preview-wrap")).to_have_count(2)
                payload = next(payload for _, path, payload in reversed(self.calls) if path == "canvas/generate")
                self.assertEqual(payload["retagDropTags"], [character])
                self.assertEqual(payload["retagPrompt"], source)
                self.assertEqual(payload["raw"], raw)
                expect(chip).to_have_attribute("aria-pressed", "true")
                chip.click()
                self.page.locator(".generate-btn").click()
                expect(self.page.locator(".image-preview-wrap")).to_have_count(3)
                payload = next(payload for _, path, payload in reversed(self.calls) if path == "canvas/generate")
                self.assertEqual(payload["retagDropTags"], [])
                expect(chip).to_have_attribute("aria-pressed", "false")

    def assert_viewer_icons_centered(self):
        for selector in ("#imageViewerFoldBtn", "#imageViewerPrevBtn", "#imageViewerNextBtn"):
            button = self.page.locator(selector).bounding_box()
            icon = self.page.locator(selector + " svg").bounding_box()
            self.assertAlmostEqual(icon["x"] + icon["width"] / 2, button["x"] + button["width"] / 2, delta=.5)
            self.assertAlmostEqual(icon["y"] + icon["height"] / 2, button["y"] + button["height"] / 2, delta=.5)

    def assert_character_coordinates_centered(self, *, same_row=True):
        row = self.page.locator(".retag-character-row.is-active .retag-character-row-head")
        head = row.bounding_box()
        coordinates = row.locator(".retag-character-center-summary").bounding_box()
        label = row.locator(".retag-character-enabled").bounding_box()
        actions = row.locator(".retag-character-delete-actions").bounding_box()
        self.assertAlmostEqual(coordinates["x"] + coordinates["width"] / 2, head["x"] + head["width"] / 2, delta=.75)
        if same_row:
            self.assertAlmostEqual(coordinates["y"] + coordinates["height"] / 2, label["y"] + label["height"] / 2, delta=.75)
        self.assert_disjoint(coordinates, label)
        self.assert_disjoint(coordinates, actions)

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

    def test_toast_tracks_available_image_area_and_restores_window_center(self):
        self.open_image()
        self.page.locator("#imageViewerCopyAllBtn").click()
        notification = self.page.locator(".toast")
        expect(notification).to_have_text("复制全部信息成功")

        def check_center(expected=None):
            self.page.wait_for_function("""expected => {
                const stage = document.getElementById('imageViewerStage');
                if (stage.getAnimations().some(animation => animation.playState === 'running')) return false;
                const notification = document.querySelector('.toast');
                if (!notification) return false;
                const bounds = notification.getBoundingClientRect();
                const area = stage.getBoundingClientRect();
                const target = expected ?? (area.x + area.width / 2);
                return Math.abs(bounds.x + bounds.width / 2 - target) <= 1;
            }""", arg=expected)
            if expected is None:
                area = self.page.locator("#imageViewerStage").bounding_box()
                expected = area["x"] + area["width"] / 2
            bounds = notification.bounding_box()
            self.assertIsNotNone(bounds)
            self.assertAlmostEqual(bounds["x"] + bounds["width"] / 2, expected, delta=1)

        for width, height in ((1440, 900), (1024, 768), (390, 844)):
            with self.subTest(viewport=(width, height)):
                self.page.set_viewport_size({"width": width, "height": height})
                self.page.wait_for_timeout(350)
                stage = self.page.locator("#imageViewerStage").bounding_box()
                check_center()
                self.screenshot(f"viewer-toast-{width}-expanded.png")
                self.page.locator("#imageViewerFoldBtn").click()
                self.page.wait_for_timeout(350)
                check_center(width / 2)
                self.screenshot(f"viewer-toast-{width}-folded.png")
                self.page.locator("#imageViewerFoldBtn").click()
                self.page.wait_for_timeout(350)
                stage = self.page.locator("#imageViewerStage").bounding_box()
                check_center()
                # Renew the toast between viewports; each individual transition keeps the same notification.
                self.page.locator("#imageViewerCopyAllBtn").click()
        self.page.keyboard.press("Escape")
        check_center(390 / 2)

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
        expect(self.page.locator("#imageViewerRetagBtn")).to_have_count(0)
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
                self.assert_disjoint(next_button, fold_button)
                self.assertAlmostEqual(fold_button["y"] + fold_button["height"] / 2, height / 2, delta=1)
                self.assertEqual(fold_button["width"], 26 if width > 760 else 36)
                self.assertEqual(fold_button["height"], 58 if width > 760 else 52)
                self.assert_viewer_icons_centered()
                self.page.locator("#imageViewerFoldBtn").click()
                self.page.wait_for_timeout(350)
                self.assert_viewer_icons_centered()
                self.assert_disjoint(
                    self.page.locator("#imageViewerNextBtn").bounding_box(),
                    self.page.locator("#imageViewerFoldBtn").bounding_box(),
                )
                self.page.locator("#imageViewerFoldBtn").click()
                self.page.wait_for_timeout(350)
        self.screenshot("viewer-mobile.png")

    def test_character_editors_support_copy_cut_and_paste(self):
        self.open_role_editor()
        for label, value in (("正面", "blue hair, smile"), ("负面", "closed eyes")):
            with self.subTest(field=label):
                field = self.page.get_by_role("textbox", name=f"角色 1{label}提示词")
                field.click()
                field.press("Control+a")
                field.press("Control+c")
                self.assertEqual(self.page.evaluate("navigator.clipboard.readText()"), value)
                field.press("Control+x")
                expect(field).to_have_value("")
                self.assertEqual(self.page.evaluate("navigator.clipboard.readText()"), value)
                field.press("Control+v")
                expect(field).to_have_value(value)
        self.screenshot("character-editor.png")

    def test_character_focus_and_selection_survive_canvas_redraw(self):
        self.open_role_editor()
        self.page.locator(".retag-character-marker").nth(1).click()
        field = self.page.get_by_role("textbox", name="角色 2负面提示词")
        field.click()
        field.press("Control+a")
        # Fit view rebuilds nodes while the native text field still owns focus.
        field.press("Control+0")
        expect(field).to_be_focused()
        self.assertEqual(field.evaluate("el => [el.selectionStart, el.selectionEnd]"), [0, len("glasses")])
        field.press("Control+c")
        self.assertEqual(self.page.evaluate("navigator.clipboard.readText()"), "glasses")

    def test_character_buttons_work_on_first_click_and_have_clear_layout(self):
        self.open_role_editor()
        layouts = self.page.locator(".retag-character-layout")
        boxes = [layouts.nth(index).bounding_box() for index in range(4)]
        self.assertAlmostEqual(boxes[0]["y"], boxes[1]["y"], delta=1)
        self.assertAlmostEqual(boxes[2]["y"], boxes[3]["y"], delta=1)
        self.assertGreater(boxes[2]["y"], boxes[0]["y"] + boxes[0]["height"])
        self.assertAlmostEqual(boxes[0]["width"], boxes[1]["width"], delta=1)
        self.page.get_by_role("button", name="均匀横向", exact=True).click()
        marker = self.page.locator(".retag-character-marker").first
        self.assertAlmostEqual(marker.evaluate("el => parseFloat(el.style.left)"), 100 / 3, delta=.001)
        self.page.get_by_role("button", name="删除角色 1", exact=True).click()
        expect(self.page.get_by_role("button", name="确认删除角色 1", exact=True)).to_be_visible()
        self.assert_character_coordinates_centered()
        self.assert_disjoint(
            self.page.locator(".retag-character-row.is-active .retag-character-delete-actions").bounding_box(),
            self.page.locator(".retag-character-row.is-active .retag-character-center-summary").bounding_box(),
        )
        self.page.get_by_role("button", name="取消删除", exact=True).click()
        self.assert_character_coordinates_centered()
        self.page.get_by_role("button", name="清空角色", exact=True).click()
        expect(self.page.locator(".retag-character-marker")).to_have_count(0)
        self.page.get_by_role("button", name="添加角色", exact=True).click()
        expect(self.page.locator(".retag-character-marker")).to_have_count(1)
        self.page.get_by_role("textbox", name="角色 1正面提示词").fill("smile")
        expect(self.page.locator(".retag-character-card .retag-layer-summary")).to_contain_text("1/1 有效")
        self.page.locator(".retag-character-row.is-active .retag-character-enabled input").uncheck()
        self.assertIn("is-disabled", self.page.locator(".retag-character-marker").get_attribute("class"))

    def test_zero_rescale_matches_the_outgoing_request(self):
        self.open_role_editor()
        node = next(item for item in self.workspace["nodes"] if item["type"] == "prompt")
        node["y"] = 110
        node["meta"].update({"retagCharacterExpanded": False, "advParamsExpanded": True, "cfgRescale": 0, "retagCfgRescale": .35, "negativePrompt": ""})
        self.page.reload()
        field = self.page.locator(".adv-field").nth(2)
        expect(field.locator(".adv-value")).to_have_text("0.00 •")
        expect(field.locator("input")).to_have_value("0")
        self.page.locator(".generate-btn").click()
        expect(self.page.locator(".image-preview-wrap")).to_have_count(1)
        payload = next(payload for _, path, payload in reversed(self.calls) if path == "canvas/generate")
        self.assertEqual(payload["cfg_rescale"], 0)
        self.assertEqual(payload["negative_prompt"], "")

    def test_reuse_creates_editable_node_and_passes_image_parameters(self):
        self.open_image()
        self.page.locator("#imageViewerReuseBtn").click()
        expect(self.page.locator("#imageViewer")).to_be_hidden()
        expect(self.page.locator(".prompt-text")).to_have_value(RAW_TAGS)
        expect(self.page.get_by_role("textbox", name="节点负面提示词")).to_have_value("lowres, blurry")
        expect(self.page.get_by_role("textbox", name="生成种子")).to_have_value("111")
        self.assertFalse(any(path == "canvas/generate" for _, path, _ in self.calls))
        self.page.get_by_role("textbox", name="生成种子").fill("222")
        self.page.get_by_role("textbox", name="节点负面提示词").fill("soft focus")
        self.page.locator(".generate-btn").click()
        expect(self.page.locator(".image-preview-wrap")).to_have_count(3)
        payload = next(payload for _, path, payload in reversed(self.calls) if path == "canvas/generate")
        self.assertEqual(payload["prompt"], RAW_TAGS)
        self.assertEqual(payload["seed"], 222)
        self.assertEqual(payload["model"], "nai-diffusion-4-5-full")
        self.assertEqual(payload["ratio"], "960x640")
        self.assertEqual(payload["negative_prompt"], "soft focus")
        self.assertEqual(payload["cfg_rescale"], 0)
        self.assertEqual(payload["noise_schedule"], "karras")
        self.assertEqual(payload["sampler"], "k_euler_ancestral")
        self.assertEqual(payload["retagCharPrompts"][0]["center"], {"x": .17, "y": .53})
        self.assertTrue(payload["raw"])

    def test_preview_navigation_keeps_fold_state(self):
        self.open_image()
        self.page.locator("#imageViewerFoldBtn").click()
        self.page.locator("#imageViewerNextBtn").click()
        expect(self.page.locator("#imageViewerTitle")).to_have_text("Image B")
        self.assertIn("folded", self.page.locator("#imageViewer").get_attribute("class").split())
        expect(self.page.locator("#imageViewerFoldBtn")).to_have_attribute("aria-expanded", "false")

    def test_character_editor_stays_inside_narrow_viewport(self):
        self.open_role_editor()
        for width in (700, 390, 260):
            with self.subTest(width=width):
                self.page.set_viewport_size({"width": width, "height": 900})
                self.page.wait_for_timeout(100)
                box = self.page.locator(".retag-character-editor-popover").bounding_box()
                self.assertGreaterEqual(box["x"], 10)
                self.assertLessEqual(box["x"] + box["width"], width - 10)
                self.assertGreaterEqual(box["y"], 10)
                self.assertLessEqual(box["y"] + box["height"], 890)
                self.assert_character_coordinates_centered(same_row=width > 260)
        self.page.get_by_role("button", name="关闭角色编辑", exact=True).click()
        expect(self.page.locator(".retag-character-editor-popover")).to_be_hidden()
        self.page.locator(".retag-character-marker").first.click()
        expect(self.page.locator(".retag-character-editor-popover")).to_be_visible()

    def test_library_only_reads_visible_thumbnails_until_preview(self):
        self.library = [{"id": f"{index:032x}", "name": f"素材 {index}", "artist": "测试画师", "width": 960, "height": 640, "seed": index, "tags": "landscape"} for index in range(1, 201)]
        self.page.reload()
        self.calls.clear()
        self.page.locator("#assetLibraryBtn").click()
        self.page.locator(".asset-stack-card").first.click()
        self.page.wait_for_timeout(200)
        thumbs = [path for _, path, _ in self.calls if path == "canvas/asset/thumbnail"]
        self.assertGreater(len(thumbs), 0)
        self.assertLess(len(thumbs), 200)
        self.assertFalse(any(path == "canvas/asset" for _, path, _ in self.calls))
        self.page.locator(".asset-image-card").first.click()
        expect(self.page.locator("#imageViewer")).to_be_visible()
        self.assertEqual(sum(path == "canvas/asset" for _, path, _ in self.calls), 1)

    def test_latest_library_navigation_wins_and_close_cancels_pending_open(self):
        self.library = [{"id": letter * 32, "name": letter.upper(), "width": 960, "height": 640, "tags": "landscape", "seed": 1} for letter in ("b", "c", "d")]
        self.page.reload()
        self.page.locator("#assetLibraryBtn").click()
        self.page.locator(".asset-stack-card").first.click()
        self.page.locator(".asset-image-card").first.click()
        expect(self.page.locator("#imageViewerTitle")).to_have_text("B")
        self.page.evaluate("window.assetDelays = { ['c'.repeat(32)]: 500, ['d'.repeat(32)]: 20 }")
        self.page.locator("#imageViewerNextBtn").click()
        self.page.locator("#imageViewerNextBtn").click()
        expect(self.page.locator("#imageViewerTitle")).to_have_text("D")
        self.page.wait_for_timeout(550)
        expect(self.page.locator("#imageViewerTitle")).to_have_text("D")
        self.page.keyboard.press("Escape")
        self.library.append({"id": "e" * 32, "name": "E", "width": 960, "height": 640, "tags": "landscape", "seed": 1})
        self.page.locator("#assetRefreshBtn").click()
        self.page.evaluate("window.assetDelays['e'.repeat(32)] = 500")
        self.page.locator('[data-asset-id="' + "e" * 32 + '"]').click()
        self.page.keyboard.press("Escape")
        self.page.wait_for_timeout(550)
        expect(self.page.locator("#imageViewer")).to_be_hidden()

    def test_asset_cache_is_bounded_deduplicates_and_recovers_after_failure(self):
        result = self.page.evaluate("""async () => {
          const {AssetCache} = await import('./asset-cache.js?v=4.6.34');
          const calls = {}; let active = 0, peak = 0;
          const cache = new AssetCache(async id => {
            calls[id] = (calls[id] || 0) + 1;
            active++; peak = Math.max(peak, active);
            await new Promise(resolve => setTimeout(resolve, 5)); active--;
            if (id === 'retry' && calls[id] === 1) throw new Error('offline');
            return {dataUrl: id.repeat(4)};
          }, {maxEntries: 2, maxBytes: 40, concurrency: 2});
          await Promise.all([cache.get('a'), cache.get('a'), cache.get('b'), cache.get('c')]);
          await cache.get('retry').catch(() => {});
          const recovered = await cache.get('retry');
          return {calls, peak, size: cache.entries.size, bytes: cache.bytes, recovered: recovered.dataUrl};
        }""")
        self.assertEqual(result["calls"]["a"], 1)
        self.assertEqual(result["calls"]["retry"], 2)
        self.assertLessEqual(result["peak"], 2)
        self.assertLessEqual(result["size"], 2)
        self.assertLessEqual(result["bytes"], 40)
        self.assertTrue(result["recovered"])

    def test_archive_reads_originals_across_cache_eviction(self):
        self.library = [{"id": f"{index:032x}", "name": f"素材 {index}", "width": 960, "height": 640, "seed": index, "tags": "landscape"} for index in range(10, 24)]
        self.page.reload()
        self.page.locator("#assetLibraryBtn").click()
        self.page.locator("#assetSelectModeBtn").click()
        self.page.locator(".asset-stack-card").first.click()
        with self.page.expect_download() as download:
            self.page.locator("#assetArchiveSelectedBtn").click()
        with zipfile.ZipFile(download.value.path()) as archive:
            manifest = json.loads(archive.read("library-manifest.json"))
            self.assertEqual(len(manifest["assets"]), 14)
            for asset in manifest["assets"]:
                self.assertNotIn("skipped", asset)
                self.assertGreater(len(archive.read(asset["file"])), 0)

    def test_tiff_preview_download_and_archive_keep_original_format(self):
        output = BytesIO()
        Image.new("RGB", (32, 24), "red").save(output, format="TIFF")
        original = output.getvalue()
        asset_id = self.library[0]["id"]
        self.library[0]["format"] = "tiff"
        self.original_assets[asset_id] = {
            "dataUrl": "data:image/tiff;base64," + base64.b64encode(original).decode(),
            "format": "tiff",
        }
        self.page.reload()
        self.page.locator("#assetLibraryBtn").click()
        self.page.locator(".asset-stack-card").first.click()
        self.page.locator(".asset-image-card").first.click()
        expect(self.page.locator("#imageViewer")).to_be_visible()
        self.page.wait_for_function("document.getElementById('imageViewerImage').naturalWidth > 0")
        self.assertTrue(any(path == "canvas/asset" and payload.get("preview") for _, path, payload in self.calls))
        self.page.locator("#imageViewerDownloadBtn").click()
        self.page.wait_for_function("window.downloads?.length === 1")
        self.assertEqual(self.page.evaluate("window.downloads[0].filename"), f"bestnai-{asset_id}.tiff")
        self.page.keyboard.press("Escape")
        expect(self.page.locator("#imageViewer")).to_be_hidden()
        self.page.locator("#assetSelectModeBtn").click()
        self.page.locator(".asset-image-card").first.click()
        with self.page.expect_download() as download:
            self.page.locator("#assetArchiveSelectedBtn").click()
        with zipfile.ZipFile(download.value.path()) as archive:
            manifest = json.loads(archive.read("library-manifest.json"))
            item = manifest["assets"][0]
            self.assertTrue(item["file"].endswith(".tiff"))
            self.assertEqual(archive.read(item["file"]), original)

    def test_input_format_is_not_sent_as_unsupported_generation_output(self):
        result = self.page.evaluate("""async () => {
          const {generationParameterPayload} = await import('./generation-params.js?v=4.6.34');
          return ['gif', 'tiff', 'avif', 'PNG', 'JPEG', 'webp'].map(imageFormat =>
            generationParameterPayload({imageFormat}).image_format ?? null);
        }""")
        self.assertEqual(result, [None, None, None, "png", "jpg", "webp"])

    def test_failed_generation_exposes_copyable_diagnostic(self):
        self.open_role_editor()
        node = next(item for item in self.workspace["nodes"] if item["type"] == "prompt")
        node["y"] = 110
        node["meta"]["retagCharacterExpanded"] = False
        self.generation_error = "生图失败：接口访问被拦截\n\n诊断信息：\n错误类型：访问拦截\n上游 HTTP：403\n原始信息：Cloudflare blocked request"
        self.page.reload()
        self.page.locator(".generate-btn").click()
        copy_button = self.page.get_by_role("button", name="复制诊断信息", exact=True)
        expect(copy_button).to_be_visible()
        copy_button.click()
        diagnostic = self.page.evaluate("navigator.clipboard.readText()")
        self.assertIn("403", diagnostic)
        self.assertIn("Cloudflare", diagnostic)


if __name__ == "__main__":
    unittest.main()
