from __future__ import annotations

from dataclasses import dataclass, field, replace
from typing import Any, Mapping, Optional, Tuple


CropBox = Tuple[int, int, int, int]


IMAGE_PRESETS = {
    "text": {
        "method": "th",
        "threshold": 160,
        "contrast": 1.2,
        "brightness": 1.0,
        "gamma": 1.0,
        "fit": "width",
    },
    "label": {
        "method": "ordered",
        "contrast": 1.25,
        "brightness": 1.05,
        "gamma": 1.0,
        "fit": "width",
        "textDensity": "dark",
    },
    "photo": {
        "method": "fs",
        "contrast": 1.1,
        "brightness": 1.0,
        "gamma": 0.95,
        "fit": "autofit",
    },
    "sticker": {
        "method": "ordered",
        "contrast": 1.35,
        "brightness": 1.05,
        "gamma": 0.9,
        "fit": "autofit",
    },
}

TEXT_PRESETS = {
    "text": {
        "method": "th",
        "contrast": 1.2,
        "brightness": 1.0,
        "gamma": 1.0,
    },
    "label": {
        "method": "fs",
        "contrast": 1.25,
        "brightness": 1.05,
        "gamma": 1.0,
        "textDensity": "dark",
    },
}


@dataclass(frozen=True)
class DeviceSettings:
    name: str
    mac: str
    channel: int
    port: str
    baudrate: int
    rfcomm_service: str


@dataclass(frozen=True)
class PrinterSettings:
    width: int
    feed: int
    repeat: int


@dataclass(frozen=True)
class RenderSettings:
    method: str
    brightness: float
    contrast: float
    gamma: float


@dataclass(frozen=True)
class TextSettings:
    font: str
    font_size: int
    pad_y: int
    align: str
    line_spacing: float
    density: str


@dataclass(frozen=True)
class ImageSettings:
    rotate: int
    rotate_explicit: bool
    crop: Optional[CropBox]
    fit: str
    height: Optional[int]
    crop_align: str
    invert: bool
    threshold: Optional[int]


@dataclass(frozen=True)
class RuntimeSettings:
    device: DeviceSettings
    printer: PrinterSettings
    render: RenderSettings
    text: TextSettings
    image: ImageSettings
    preview: bool = False
    preset: Optional[str] = None


@dataclass(frozen=True)
class TextJob:
    text: str
    settings: RuntimeSettings
    job_id: Optional[str] = None


@dataclass(frozen=True)
class ImageJob:
    path: str
    settings: RuntimeSettings
    job_id: Optional[str] = None


@dataclass(frozen=True)
class RenderResult:
    success: bool
    image: Any = None
    raster: Optional[bytes] = None
    warnings: Tuple[str, ...] = ()
    error: Optional[str] = None
    metadata: Mapping[str, Any] = field(default_factory=dict)


@dataclass(frozen=True)
class PrintResult:
    success: bool
    bytes_written: int = 0
    warnings: Tuple[str, ...] = ()
    error: Optional[str] = None
    metadata: Mapping[str, Any] = field(default_factory=dict)


def runtime_settings_from_config(
    config: Mapping[str, Any],
    *,
    default_image_rotate: int = 0,
) -> RuntimeSettings:
    device = config["device"]
    printer = config["printer"]
    text = config["text"]
    image = config["image"]

    return RuntimeSettings(
        device=DeviceSettings(
            name=device["name"],
            mac=device["mac"],
            channel=device["channel"],
            port=device["port"],
            baudrate=device["baudrate"],
            rfcomm_service=device["rfcommService"],
        ),
        printer=PrinterSettings(
            width=printer["width"],
            feed=printer["feed"],
            repeat=printer["repeat"],
        ),
        render=RenderSettings(
            method=image["method"],
            brightness=image["brightness"],
            contrast=image["contrast"],
            gamma=image["gamma"],
        ),
        text=TextSettings(
            font=text["font"],
            font_size=text["fontSize"],
            pad_y=text["padY"],
            align=text["align"],
            line_spacing=text["lineSpacing"],
            density=text["density"],
        ),
        image=ImageSettings(
            rotate=image["rotate"],
            rotate_explicit=image["rotate"] != default_image_rotate,
            crop=None,
            fit=image["fit"],
            height=image["height"],
            crop_align=image["cropAlign"],
            invert=image["invert"],
            threshold=image["threshold"],
        ),
    )


def resolve_runtime_settings(
    config: Mapping[str, Any],
    *,
    command: Optional[str] = None,
    preset: Optional[str] = None,
    overrides: Optional[Mapping[str, Any]] = None,
    text_presets: Optional[Mapping[str, Mapping[str, Any]]] = None,
    image_presets: Optional[Mapping[str, Mapping[str, Any]]] = None,
    default_image_rotate: int = 0,
) -> RuntimeSettings:
    settings = runtime_settings_from_config(
        config,
        default_image_rotate=default_image_rotate,
    )
    settings = apply_preset_defaults(
        settings,
        command=command,
        preset=preset,
        text_presets=text_presets,
        image_presets=image_presets,
    )
    return apply_runtime_overrides(settings, command=command, overrides=overrides)


def apply_preset_defaults(
    settings: RuntimeSettings,
    *,
    command: Optional[str],
    preset: Optional[str],
    text_presets: Optional[Mapping[str, Mapping[str, Any]]] = None,
    image_presets: Optional[Mapping[str, Mapping[str, Any]]] = None,
) -> RuntimeSettings:
    if not preset:
        return settings

    if command == "text":
        presets = TEXT_PRESETS if text_presets is None else text_presets
    else:
        presets = IMAGE_PRESETS if image_presets is None else image_presets

    if presets is None or preset not in presets:
        raise ValueError(f"Unknown preset for {command or 'command'}: {preset}")

    return apply_option_defaults(settings, presets[preset], preset=preset)


def apply_option_defaults(
    settings: RuntimeSettings,
    defaults: Mapping[str, Any],
    *,
    preset: Optional[str] = None,
) -> RuntimeSettings:
    render = settings.render
    text = settings.text
    image = settings.image

    if "brightness" in defaults:
        render = replace(render, brightness=defaults["brightness"])
    if "contrast" in defaults:
        render = replace(render, contrast=defaults["contrast"])
    if "gamma" in defaults:
        render = replace(render, gamma=defaults["gamma"])
    if "method" in defaults:
        render = replace(render, method=defaults["method"])
    if "fit" in defaults:
        image = replace(image, fit=defaults["fit"])
    if "threshold" in defaults:
        image = replace(image, threshold=defaults["threshold"])
    if "textDensity" in defaults:
        text = replace(text, density=defaults["textDensity"])

    return replace(settings, render=render, text=text, image=image, preset=preset)


def apply_runtime_overrides(
    settings: RuntimeSettings,
    *,
    command: Optional[str],
    overrides: Optional[Mapping[str, Any]],
) -> RuntimeSettings:
    if not overrides:
        return settings

    render = settings.render
    printer = settings.printer
    text = settings.text
    image = settings.image
    preview = settings.preview

    if "brightness" in overrides:
        render = replace(render, brightness=overrides["brightness"])
    if "contrast" in overrides:
        render = replace(render, contrast=overrides["contrast"])
    if "gamma" in overrides:
        render = replace(render, gamma=overrides["gamma"])
    if "method" in overrides:
        render = replace(render, method=overrides["method"])
    if "feed" in overrides:
        printer = replace(printer, feed=overrides["feed"])
    if "repeat" in overrides:
        printer = replace(printer, repeat=overrides["repeat"])
    if "preview" in overrides:
        preview = overrides["preview"]

    if command == "img":
        if "rotate" in overrides:
            image = replace(
                image,
                rotate=overrides["rotate"],
                rotate_explicit=True,
            )
        if "crop" in overrides:
            image = replace(image, crop=overrides["crop"])
        if "fit" in overrides:
            image = replace(image, fit=overrides["fit"])
        if "height" in overrides:
            image = replace(image, height=overrides["height"])
        if "crop_align" in overrides:
            image = replace(image, crop_align=overrides["crop_align"])
        if "invert" in overrides:
            image = replace(image, invert=overrides["invert"])
        if "threshold" in overrides:
            image = replace(image, threshold=overrides["threshold"])

    if command == "text":
        if "size" in overrides:
            text = replace(text, font_size=overrides["size"])
        if "pad_y" in overrides:
            text = replace(text, pad_y=overrides["pad_y"])
        if "line_spacing" in overrides:
            text = replace(text, line_spacing=overrides["line_spacing"])
        if "align" in overrides:
            text = replace(text, align=overrides["align"])
        if "text_density" in overrides:
            text = replace(text, density=overrides["text_density"])

    return replace(
        settings,
        printer=printer,
        render=render,
        text=text,
        image=image,
        preview=preview,
    )
