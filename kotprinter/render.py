from __future__ import annotations

import textwrap
from typing import Iterable

try:
    from PIL import Image, ImageDraw, ImageEnhance, ImageFilter, ImageFont, ImageOps
except ImportError:
    Image = ImageDraw = ImageEnhance = ImageFilter = ImageFont = ImageOps = None

from .core import ImageJob, ImageSettings, RenderResult, RuntimeSettings, TextJob


class RenderError(Exception):
    pass


class RenderDependencyError(RenderError):
    pass


def render_text_job(job: TextJob) -> RenderResult:
    require_pillow_dependency()

    settings = job.settings
    img = render_text_source_image(job.text, settings)
    img = preprocess_image(img, settings)
    img = apply_text_density(img, settings.text.density)

    return RenderResult(
        success=True,
        image=img,
        metadata={
            "type": "text",
            "width": img.width,
            "height": img.height,
            "mode": img.mode,
        },
    )


def render_image_job(job: ImageJob) -> RenderResult:
    require_pillow_dependency()

    settings = job.settings
    img = load_image(job.path)
    img, warnings = apply_image_geometry(img, settings)
    img = preprocess_image(
        img,
        settings,
        invert=settings.image.invert,
        threshold=settings.image.threshold,
    )

    return RenderResult(
        success=True,
        image=img,
        warnings=warnings,
        metadata={
            "type": "image",
            "source": job.path,
            "width": img.width,
            "height": img.height,
            "mode": img.mode,
        },
    )


def require_pillow_dependency() -> None:
    if Image is None:
        raise RenderDependencyError(
            "Pillow is not installed. Install it with "
            '`python3 -m pip install "Pillow"`.'
        )


def load_font(path: str, font_size: int):
    try:
        return ImageFont.truetype(path, font_size)
    except Exception:
        return ImageFont.load_default()


def get_font_height(font) -> int:
    if hasattr(font, "getmetrics"):
        ascent, descent = font.getmetrics()
        return ascent + descent

    bbox = font.getbbox("Mg")
    return bbox[3] - bbox[1]


def render_text_source_image(text: str, settings: RuntimeSettings):
    font = load_font(settings.text.font, settings.text.font_size)
    text = text.replace("\\n", "\n").replace("\\t", "\t")
    lines = wrap_text_to_width(text, font, settings.printer.width)

    font_height = get_font_height(font)
    line_heights = [font_height for _ in lines]
    total_height = sum(line_heights)

    line_spacing_px = settings.text.font_size * settings.text.line_spacing
    if len(lines) > 1:
        total_height += line_spacing_px * (len(lines) - 1)

    img = Image.new(
        "L",
        (settings.printer.width, int(total_height + settings.text.pad_y * 2)),
        255,
    )
    draw = ImageDraw.Draw(img)

    y_offset = settings.text.pad_y
    for i, line in enumerate(lines):
        line = line.replace("\t", "    ")
        if line.strip():
            bbox = font.getbbox(line)
            text_w = bbox[2] - bbox[0]

            if settings.text.align == "center":
                x = (settings.printer.width - text_w) // 2
            elif settings.text.align == "right":
                x = settings.printer.width - text_w
            else:
                x = 0

            draw.text((max(0, x), int(y_offset)), line, font=font, fill=0)

        y_offset += line_heights[i]
        if i < len(lines) - 1:
            y_offset += line_spacing_px

    return img


def wrap_text_to_width(text: str, font, max_w: int) -> list[str]:
    lines_out = []
    for line in text.split("\n"):
        if not line.strip():
            lines_out.append("")
            continue

        avg = font.getlength("M")
        approx = max(1, int(max_w // max(1, avg)))
        for chunk in textwrap.wrap(line, width=approx, break_long_words=True):
            while font.getlength(chunk) > max_w and len(chunk) > 1:
                chunk = chunk[:-1]
            lines_out.append(chunk)

    return lines_out


def load_image(path: str):
    try:
        with Image.open(path) as img:
            return ImageOps.exif_transpose(img).copy()
    except FileNotFoundError as e:
        raise RenderError(f"Image file not found: {path}") from e
    except Image.UnidentifiedImageError as e:
        raise RenderError(f"Cannot read image file: {path}: {e}") from e
    except OSError as e:
        raise RenderError(f"Cannot read image file: {path}: {e}") from e


def apply_image_geometry(img, settings: RuntimeSettings):
    warnings = []
    img, selected_rotate = apply_image_rotation(img, settings.image)
    img = apply_image_crop(img, settings.image)

    fit_mode = settings.image.fit
    if settings.image.fit == "autofit":
        fit_mode = choose_autofit_mode(img, settings)
        autofit_message = f"autofit: rotate={selected_rotate}, fit={fit_mode}"
        if settings.image.height is not None:
            autofit_message += f", height={settings.image.height}"
        warnings.append(autofit_message)

    img = apply_image_fit(img, fit_mode, settings)
    return img, tuple(warnings)


def apply_image_rotation(img, image_settings: ImageSettings):
    rotate = image_settings.rotate
    if (
        image_settings.fit == "autofit"
        and not image_settings.rotate_explicit
        and _is_landscape(img)
    ):
        rotate = 90

    if rotate:
        img = rotate_image(img, rotate)

    return img, rotate


def rotate_image(img, degrees: int):
    rotations = {
        0: None,
        90: Image.Transpose.ROTATE_270,
        180: Image.Transpose.ROTATE_180,
        270: Image.Transpose.ROTATE_90,
    }
    transpose = rotations[degrees]
    return img if transpose is None else img.transpose(transpose)


def apply_image_crop(img, image_settings: ImageSettings):
    if image_settings.crop is None:
        return img

    left, top, width, height = image_settings.crop
    right = left + width
    bottom = top + height
    if right > img.width or bottom > img.height:
        raise RenderError(
            f"Crop {left},{top},{width},{height} exceeds image bounds "
            f"{img.width}x{img.height}"
        )

    return img.crop((left, top, right, bottom))


def choose_autofit_mode(img, settings: RuntimeSettings) -> str:
    if settings.image.height is None:
        return "width"

    target_ratio = settings.printer.width / settings.image.height
    source_ratio = img.width / img.height

    visible_fraction = min(source_ratio / target_ratio, target_ratio / source_ratio)
    aspect_loss = max(0.0, 1.0 - visible_fraction)
    return "cover" if aspect_loss <= 0.15 else "contain"


def apply_image_fit(img, fit_mode: str, settings: RuntimeSettings):
    printer_width = settings.printer.width
    target_height = settings.image.height

    if fit_mode == "width":
        return resize_to_width(img, printer_width)
    if fit_mode == "none":
        return pad_or_crop_to_width(img, printer_width)
    if fit_mode == "stretch":
        require_image_height(fit_mode, target_height)
        return img.resize((printer_width, target_height), Image.LANCZOS)
    if fit_mode == "contain":
        require_image_height(fit_mode, target_height)
        return contain_image(img, printer_width, target_height)
    if fit_mode == "cover":
        require_image_height(fit_mode, target_height)
        return cover_image(
            img,
            printer_width,
            target_height,
            settings.image.crop_align,
        )

    raise RenderError(f"Unsupported fit mode: {fit_mode}")


def resize_to_width(img, target_width: int):
    if img.width == target_width:
        return img

    target_height = max(1, round(img.height * target_width / img.width))
    return img.resize((target_width, target_height), Image.LANCZOS)


def contain_image(img, target_width: int, target_height: int):
    scale = min(target_width / img.width, target_height / img.height)
    new_size = (
        max(1, round(img.width * scale)),
        max(1, round(img.height * scale)),
    )
    resized = img.resize(new_size, Image.LANCZOS)
    canvas = Image.new(
        img.mode,
        (target_width, target_height),
        _white_for_mode(img.mode),
    )
    canvas.paste(
        resized,
        ((target_width - resized.width) // 2, (target_height - resized.height) // 2),
    )
    return canvas


def cover_image(img, target_width: int, target_height: int, crop_align: str):
    scale = max(target_width / img.width, target_height / img.height)
    new_size = (
        max(1, round(img.width * scale)),
        max(1, round(img.height * scale)),
    )
    resized = img.resize(new_size, Image.LANCZOS)

    left = max(0, (resized.width - target_width) // 2)
    if crop_align == "top":
        top = 0
    elif crop_align == "bottom":
        top = max(0, resized.height - target_height)
    else:
        top = max(0, (resized.height - target_height) // 2)

    return resized.crop((left, top, left + target_width, top + target_height))


def require_image_height(fit_mode: str, image_height: int | None) -> None:
    if image_height is None:
        raise RenderError(f"--height is required when --fit {fit_mode} is used")


def preprocess_image(
    img,
    settings: RuntimeSettings,
    *,
    invert: bool = False,
    threshold: int | None = None,
):
    if img.mode != "L":
        img = img.convert("L")

    if settings.render.brightness != 1.0:
        img = ImageEnhance.Brightness(img).enhance(settings.render.brightness)
    if settings.render.contrast != 1.0:
        img = ImageEnhance.Contrast(img).enhance(settings.render.contrast)
    if settings.render.gamma != 1.0:
        lut = [
            min(255, int(((i / 255.0) ** (1.0 / settings.render.gamma)) * 255 + 0.5))
            for i in range(256)
        ]
        img = img.point(lut, mode="L")

    if invert:
        img = ImageOps.invert(img)

    if threshold is not None:
        return img.point(lambda x: 0 if x < threshold else 255, "1")

    if settings.render.method == "fs":
        img = img.convert("1")
    elif settings.render.method == "ordered":
        img = img.convert("1", dither=Image.Dither.NONE)
        img = ImageOps.posterize(img.convert("L"), 1).convert("1")
    else:
        img = img.point(lambda x: 0 if x < 128 else 255, "1")

    return img


def apply_text_density(img, text_density: str):
    if text_density == "normal":
        return img

    if img.mode != "1":
        img = img.convert("1")
    img = img.convert("L")

    if text_density == "light":
        px = img.load()
        for y in range(img.height):
            for x in range(img.width):
                if px[x, y] == 0 and (x + y) % 3 == 0:
                    px[x, y] = 255
        return img.convert("1", dither=Image.Dither.NONE)

    if text_density == "dark":
        img = img.filter(ImageFilter.MinFilter(3))
        return img.point(lambda x: 0 if x < 255 else 255, "1")

    return img.convert("1", dither=Image.Dither.NONE)


def img_to_escpos_raster(img, printer_width: int) -> bytes:
    img = prepare_raster_image(img, printer_width)
    return _prepared_img_to_escpos_raster(img)


def img_to_escpos_raster_bands(
    img,
    printer_width: int,
    band_height: int,
) -> Iterable[bytes]:
    img = prepare_raster_image(img, printer_width)
    band_height = max(1, band_height)
    for top in range(0, img.height, band_height):
        bottom = min(top + band_height, img.height)
        band = img.crop((0, top, img.width, bottom))
        yield _prepared_img_to_escpos_raster(band)


def prepare_raster_image(img, printer_width: int):
    if img.mode != "1":
        img = img.convert("L")
        img = img.point(lambda x: 0 if x < 128 else 255, "1")

    if img.width > printer_width:
        new_height = int(img.height * printer_width / img.width)
        img = img.resize((printer_width, new_height), Image.LANCZOS)

    if img.width < printer_width:
        left_pad = (printer_width - img.width) // 2
        canvas = Image.new("1", (printer_width, img.height), 1)
        canvas.paste(img, (left_pad, 0))
        img = canvas

    return img


def _prepared_img_to_escpos_raster(img) -> bytes:
    if img.width % 8:
        raise ValueError("Raster image width must be divisible by 8")

    px = img.load()
    x_bytes = img.width // 8
    data = bytearray()
    for y in range(img.height):
        for xb in range(0, img.width, 8):
            b = 0
            for bit in range(8):
                b <<= 1
                if px[xb + bit, y] == 0:
                    b |= 1
            data.append(b)

    cmd = b"\x1D\x76\x30\x00"
    cmd += bytes(
        [
            x_bytes & 0xFF,
            (x_bytes >> 8) & 0xFF,
            img.height & 0xFF,
            (img.height >> 8) & 0xFF,
        ]
    )
    cmd += data
    return cmd


def pad_or_crop_to_width(img, target_width: int):
    if img.width == target_width:
        return img

    if img.width > target_width:
        left = (img.width - target_width) // 2
        return img.crop((left, 0, left + target_width, img.height))

    left_pad = (target_width - img.width) // 2
    canvas = Image.new(img.mode, (target_width, img.height), _white_for_mode(img.mode))
    canvas.paste(img, (left_pad, 0))
    return canvas


def _white_for_mode(mode: str):
    if mode == "1":
        return 1
    if mode == "L":
        return 255
    return "white"


def _is_landscape(img) -> bool:
    return img.width > img.height * 1.1
