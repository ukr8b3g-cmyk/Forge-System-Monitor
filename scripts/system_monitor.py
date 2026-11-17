"""Register Forge settings and a read-only, authenticated sampling route."""

import gradio as gr
from fastapi import Depends
from fastapi.responses import JSONResponse

from modules import script_callbacks, shared
from modules.options import categories

from forge_system_monitor.sensors import Sampler, japanese_locale

PREFIX = "forge_system_monitor_"
ROUTE = "/internal/forge-system-monitor"
MONITOR = Sampler()
METRICS = {
    "CPU": "cpu", "RAM": "ram", "GPU": "gpu", "VRAM": "vram", "GPU Temperature": "temp",
}
INTERVALS = {"1 second": 1, "2 seconds": 2, "5 seconds": 5}
LEGACY_DROPDOWN = gr.__version__.split(".", 1)[0] == "3"
CHOICE_JA = {
    "Below generation controls": "生成欄の下", "Floating": "フローティング",
    "Bottom right": "右下", "Bottom left": "左下", "Top right": "右上", "Top left": "左上",
    "Auto": "自動", "English": "英語", "Japanese": "日本語", "GPU Temperature": "GPU 温度",
    "1 second": "1秒", "2 seconds": "2秒", "5 seconds": "5秒",
}
CANONICAL_VALUE = {label: value for value, label in CHOICE_JA.items()}


def option(key, default=None):
    return getattr(shared.opts, PREFIX + key, default)


def text(english, japanese):
    return japanese if japanese_locale(getattr(shared.opts, "localization", "")) else english


class LegacyChoices:
    """Gradio 3 displays string choices. Keep saved values independent of the locale."""

    def __init__(self, *, choices, **kwargs):
        self.values = {label: CANONICAL_VALUE.get(label, label) for label in choices}
        self.labels = {value: label for label, value in self.values.items()}
        super().__init__(choices=choices, **kwargs)

    @staticmethod
    def translate(value, mapping):
        if isinstance(value, list):
            return [mapping.get(item, item) for item in value]
        return mapping.get(value, value)

    def preprocess(self, value):
        return self.translate(super().preprocess(value), self.values)

    def postprocess(self, value):
        return super().postprocess(self.translate(value, self.labels))


if LEGACY_DROPDOWN:
    class LegacyDropdown(LegacyChoices, gr.Dropdown):
        def get_block_name(self):
            return "dropdown"

    class LegacyCheckboxGroup(LegacyChoices, gr.CheckboxGroup):
        def get_block_name(self):
            return "checkboxgroup"


def register_settings():
    category = next((key for key, item in categories.mapping.items() if item.label == "Extensions"), None)
    if category is None:
        category = PREFIX + "extensions"
        categories.register_category(category, "Extensions")
    section = (PREFIX.rstrip("_"), text("System Monitor", "システムモニター"))
    dropdown = LegacyDropdown if LEGACY_DROPDOWN else gr.Dropdown
    checkbox_group = LegacyCheckboxGroup if LEGACY_DROPDOWN else gr.CheckboxGroup

    def add(key, default, english, japanese, component=None, args=None, help_en="", help_ja=""):
        info = shared.OptionInfo(
            default, text(english, japanese), component=component, component_args=args,
            section=section, category_id=category,
        )
        if help_en:
            info.info(text(help_en, help_ja))
        shared.opts.add_option(PREFIX + key, info)

    def choices(values):
        localized = [(text(value, CHOICE_JA.get(value, value)), value) for value in values]
        # Forge sends these same arguments during its native settings refresh.
        # Gradio 3 converts a tuple in that update into a comma-separated label.
        return {"choices": [label for label, _ in localized] if LEGACY_DROPDOWN else localized}

    def gpu_choices():
        labels = ["Auto", *MONITOR.adapters()]
        saved = option("gpu", "Auto")
        if saved not in labels:
            labels.append(saved)
        return choices(labels)

    add("enabled", True, "Show monitor", "モニターを表示")
    add("position", "Below generation controls", "Position", "表示位置", dropdown, choices([
        "Below generation controls", "Floating",
    ]))
    add("corner", "Bottom right", "Corner", "固定位置", dropdown, choices([
        "Bottom right", "Bottom left", "Top right", "Top left",
    ]))
    add("language", "Auto", "Monitor language", "表示言語", dropdown, choices([
        "Auto", "English", "Japanese",
    ]), "Auto follows the WebUI localization.", "自動は WebUI のロケールに合わせます。")
    add("metrics", list(METRICS), "Metrics to show", "表示する項目", checkbox_group, choices(METRICS))
    add("interval", "2 seconds", "Update interval", "更新間隔", dropdown, choices(INTERVALS))
    add("gpu", "Auto", "GPU to monitor", "監視する GPU", dropdown, gpu_choices,
        "Auto uses the active compute GPU when it can be identified.",
        "自動では生成に使用する GPU を特定できる場合に選びます。")


def register_api(demo, app):
    if demo is None or any(getattr(route, "path", None) == ROUTE for route in app.routes):
        return
    # Use Gradio's existing guard for both its cookie formats and its auth dependency.
    login = next((route.endpoint for route in app.routes if getattr(route, "path", None) == "/login_check"), None)
    if login is None and (getattr(app, "auth", None) is not None or getattr(app, "auth_dependency", None) is not None):
        return
    dependencies = [Depends(login)] if login else []

    @app.get(ROUTE, dependencies=dependencies, include_in_schema=False)
    def read_monitor():
        values = option("metrics", list(METRICS))
        metrics = frozenset(METRICS[value] for value in values if isinstance(value, str) and value in METRICS) if isinstance(values, list) else frozenset()
        readings = {}
        if option("enabled", True) and metrics:
            readings = MONITOR.snapshot(metrics, option("gpu", "Auto"), INTERVALS.get(option("interval"), 2))
        return JSONResponse(readings, headers={"Cache-Control": "no-store"})


script_callbacks.on_ui_settings(register_settings)
script_callbacks.on_app_started(register_api)
script_callbacks.on_script_unloaded(MONITOR.close)
