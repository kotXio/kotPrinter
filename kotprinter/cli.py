from __future__ import annotations

import argparse
import os
import re
import subprocess
import sys
import termios
import textwrap
import time

try:
    import serial
except ImportError:
    serial = None

try:
    from PIL import Image, ImageDraw, ImageEnhance, ImageFilter, ImageFont, ImageOps
except ImportError:
    Image = ImageDraw = ImageEnhance = ImageFilter = ImageFont = ImageOps = None

from . import __version__
from .checks import check_exit_code, print_check_report, run_checks
from .config import ConfigError, DEFAULT_CONFIG, DEFAULT_CONFIG_NAME, load_config
from .install import InstallError, run_install


# Default RFCOMM device. Bind with: rfcomm bind /dev/rfcomm0 <MAC> 2
PORT = DEFAULT_CONFIG["device"]["port"]
RFCOMM_SERVICE = DEFAULT_CONFIG["device"]["rfcommService"]
BAUDRATE = DEFAULT_CONFIG["device"]["baudrate"]

PRN_WIDTH = DEFAULT_CONFIG["printer"]["width"]
VOLT = 0
DPI = PRN_WIDTH
FONT_PATH = DEFAULT_CONFIG["text"]["font"]

FONT_SIZE = DEFAULT_CONFIG["text"]["fontSize"]
PAD_Y = DEFAULT_CONFIG["text"]["padY"]
LINE_SPACING = DEFAULT_CONFIG["text"]["lineSpacing"]
ALIGNMENT = DEFAULT_CONFIG["text"]["align"]
BRIGHTNESS = DEFAULT_CONFIG["image"]["brightness"]
CONTRAST = DEFAULT_CONFIG["image"]["contrast"]
GAMMA = DEFAULT_CONFIG["image"]["gamma"]
METHOD = DEFAULT_CONFIG["image"]["method"]
IMAGE_ROTATE = DEFAULT_CONFIG["image"]["rotate"]
IMAGE_ROTATE_EXPLICIT = False
IMAGE_CROP = None
IMAGE_FIT = DEFAULT_CONFIG["image"]["fit"]
IMAGE_HEIGHT = DEFAULT_CONFIG["image"]["height"]
IMAGE_CROP_ALIGN = DEFAULT_CONFIG["image"]["cropAlign"]
IMAGE_INVERT = DEFAULT_CONFIG["image"]["invert"]
THRESHOLD = DEFAULT_CONFIG["image"]["threshold"]
TEXT_DENSITY = DEFAULT_CONFIG["text"]["density"]
FEED = DEFAULT_CONFIG["printer"]["feed"]
REPEAT = DEFAULT_CONFIG["printer"]["repeat"]
IS_PREVIEW = False
RASTER_BAND_HEIGHT = 64
RASTER_BAND_PAUSE = 0.12
RASTER_CHUNK_SIZE = 128
RASTER_CHUNK_PAUSE = 0.03
RASTER_JOB_PAUSE = 0.4

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

PRESETS = IMAGE_PRESETS

WAKE_RETRIES = 3
WAKE_RETRY_DELAY = 1.0
RFCOMM_REBIND_RETRIES = 2
RFCOMM_REBIND_DELAY = 0.5

# Handshake commands captured from the vendor app Bluetooth traffic.
# b"\x1E\x47\x03" returns hardware/version/voltage/DPI information.
# b"\x1D\x67\x39" returns the printer serial number.
HANDSHAKE = [
    b"\x1E\x47\x03",
    b"\x1D\x67\x39",
]
SERIAL_ERRORS = (OSError, termios.error)
if serial is not None:
    SERIAL_ERRORS = SERIAL_ERRORS + (serial.SerialException,)


def require_serial_dependency():
    if serial is None:
        print(
            '[e] pyserial is not installed. Install it with '
            '`python3 -m pip install "pyserial"`.'
        )
        sys.exit(1)


def require_pillow_dependency():
    if Image is None:
        print(
            '[e] Pillow is not installed. Install it with '
            '`python3 -m pip install "Pillow"`.'
        )
        sys.exit(1)


def is_rfcomm_bound():
    return os.path.exists(PORT)


def close_serial(ser):
    try:
        ser.close()
    except Exception:
        pass


def restart_rfcomm_service(reason, attempt, total):
    print(f"[w] {reason}")
    print(f"[i] Restarting {RFCOMM_SERVICE} to re-bind {PORT} ({attempt}/{total})")
    try:
        result = subprocess.run(
            ["sudo", "-n", "systemctl", "restart", RFCOMM_SERVICE],
            check=True,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
        )
    except FileNotFoundError as e:
        print(f"[w] Cannot restart {RFCOMM_SERVICE}: {e}")
        return False
    except subprocess.CalledProcessError as e:
        details = (e.stderr or e.stdout or str(e)).strip()
        print(f"[w] Cannot restart {RFCOMM_SERVICE}: {details}")
        return False

    if result.stdout.strip():
        print(result.stdout.strip())

    time.sleep(RFCOMM_REBIND_DELAY)
    if not is_rfcomm_bound():
        print(f"[w] {PORT} is still missing after restarting {RFCOMM_SERVICE}")
        return False

    return True


def load_font(path):
    try:
        return ImageFont.truetype(path, FONT_SIZE)
    except Exception:
        return ImageFont.load_default()


def get_font_height(font):
    if hasattr(font, "getmetrics"):
        ascent, descent = font.getmetrics()
        return ascent + descent

    bbox = font.getbbox("Mg")
    return bbox[3] - bbox[1]


def _write(ser, data, action):
    try:
        ser.write(data)
        ser.flush()
        return True
    except SERIAL_ERRORS as e:
        print(f"[e] Error {action}: {e}")
        return False


def _send(ser, data, chunk=256, pause=0.01):
    for i in range(0, len(data), chunk):
        try:
            ser.write(data[i:i + chunk])
            ser.flush()
            time.sleep(pause)
        except SERIAL_ERRORS as e:
            print(f"[e] Error sending data to printer: {e}")
            print(
                "[e] The print may be partial. Check the printer, then retry "
                "or power-cycle it."
            )
            close_serial(ser)
            sys.exit(1)


def _read(ser, size=256):
    try:
        response = ser.read(size)
        if response:
            return response
    except SERIAL_ERRORS as e:
        print(f"[e] Error reading from printer: {e}")

    return None


def get_battery_percent(voltage_mv):
    if voltage_mv >= 8000:
        return 100
    if voltage_mv <= 6800:
        return 0

    return int((voltage_mv - 6800) / (8000 - 6800) * 100)


def wake_printer(ser, quiet=False):
    if not _write(ser, HANDSHAKE[0], "sending wake handshake to printer"):
        return False

    time.sleep(0.1)
    info = _read(ser)
    if not info:
        return False

    global VOLT, DPI
    m_volt = re.search(rb"VOLT=(\d+)mv", info, re.I)
    m_dpi = re.search(rb"DPI=(\d+)", info, re.I)
    VOLT = int(m_volt.group(1)) if m_volt else 0
    DPI = int(m_dpi.group(1)) if m_dpi else PRN_WIDTH

    battery_percent = get_battery_percent(VOLT)
    if not quiet:
        print(f"[i] Printer awake: {VOLT}mV, DPI: {DPI}, Battery: {battery_percent}%")

    return True


def open_printer(retries=WAKE_RETRIES, quiet=False, rebind_retries=RFCOMM_REBIND_RETRIES):
    require_serial_dependency()

    last_error = None
    rebind_attempts = 0

    def try_rebind(reason):
        nonlocal rebind_attempts
        if rebind_attempts >= rebind_retries:
            return False

        rebind_attempts += 1
        return restart_rfcomm_service(reason, rebind_attempts, rebind_retries)

    if not is_rfcomm_bound() and not try_rebind(f"{PORT} is not bound"):
        print(f"[e] {PORT} is not bound, run `sudo systemctl restart {RFCOMM_SERVICE}`")
        sys.exit(1)

    for attempt in range(1, retries + 1):
        if not is_rfcomm_bound():
            try_rebind(f"{PORT} disappeared before opening")
            time.sleep(WAKE_RETRY_DELAY)
            continue

        try:
            ser = serial.Serial(PORT, BAUDRATE, timeout=0.7)
        except SERIAL_ERRORS as e:
            last_error = e
            print(f"[w] Cannot open {PORT} (attempt {attempt}/{retries}): {e}")
            try_rebind(f"Cannot open {PORT}")
            time.sleep(WAKE_RETRY_DELAY)
            continue

        if wake_printer(ser, quiet=quiet):
            return ser

        print(f"[w] Printer did not answer wake handshake (attempt {attempt}/{retries})")
        close_serial(ser)
        try_rebind("Printer did not answer wake handshake")
        time.sleep(WAKE_RETRY_DELAY)

    if not is_rfcomm_bound():
        print(f"[e] {PORT} is not bound, run `sudo systemctl restart {RFCOMM_SERVICE}`")
        sys.exit(1)
    if last_error:
        print(f"[e] Last serial error: {last_error}")

    print("[e] Printer did not answer. Try power-cycling it, then run the command again.")
    sys.exit(1)


def get_printer_info(ser):
    if not _write(ser, HANDSHAKE[0], "sending printer-info request"):
        sys.exit(1)

    time.sleep(0.05)
    info = _read(ser)
    if not info:
        print("[e] No response from printer")
        sys.exit(1)

    global VOLT, DPI
    m_volt = re.search(rb"VOLT=(\d+)mv", info, re.I)
    m_dpi = re.search(rb"DPI=(\d+)", info, re.I)
    VOLT = int(m_volt.group(1)) if m_volt else 0
    DPI = int(m_dpi.group(1)) if m_dpi else PRN_WIDTH

    battery_percent = get_battery_percent(VOLT)
    print(f"[i] Printer voltage: {VOLT}mV, DPI: {DPI}, Battery: {battery_percent}%")

    if not _write(ser, HANDSHAKE[1], "sending serial-number request"):
        sys.exit(1)

    time.sleep(0.05)
    serial_number = _read(ser)
    if not serial_number:
        print("[e] No response from printer for serial number")
        sys.exit(1)

    serial_number = serial_number.decode(errors="replace").rstrip("\x00").strip()
    print(f"[i] Printer serial number: {serial_number}")

    settings = [
        f"    - Printer width: {PRN_WIDTH}",
        f"    - Port: {PORT}",
        f"    - Baudrate: {BAUDRATE}",
        f"    - RFCOMM service: {RFCOMM_SERVICE}",
        f"    - Voltage: {VOLT}mv",
        f"    - DPI: {DPI}",
        f"    - Font: {FONT_PATH}",
        f"    - Font size: {FONT_SIZE}px",
        f"    - Padding (top/bottom): {PAD_Y}px",
        f"    - Line spacing: {LINE_SPACING}",
        f"    - Alignment: {ALIGNMENT}",
        f"    - Brightness: {BRIGHTNESS}",
        f"    - Contrast: {CONTRAST}",
        f"    - Gamma: {GAMMA}",
        f"    - Method: {METHOD}",
        f"    - Text density: {TEXT_DENSITY}",
        f"    - Feed: {FEED}",
        f"    - Repeat: {REPEAT}",
        f"    - Preview: {IS_PREVIEW}",
    ]
    print("[i] Printer settings:\n" + "\n".join(settings))


def escpos_init(ser):
    if not _write(ser, b"\x1B@", "initializing printer"):
        sys.exit(1)

    time.sleep(0.02)
    _read(ser)


def set_density(ser, profile="med"):
    """Send experimental density commands. The tested printer ignores them."""
    presets = {
        "low": (20, 120, 30),
        "med": (32, 160, 30),
        "high": (48, 200, 40),
    }
    if isinstance(profile, tuple) and len(profile) == 3:
        n1, n2, n3 = profile
    else:
        n1, n2, n3 = presets.get(profile, presets["med"])

    density_cmd = b"\x1B\x37" + bytes([n1 & 0xFF, n2 & 0xFF, n3 & 0xFF])
    if not _write(ser, density_cmd, "setting printer density"):
        sys.exit(1)

    time.sleep(0.02)
    _read(ser)

    level = 200 if profile == "high" else (150 if profile == "med" else 100)
    darkness_cmd = b"\x12\x23" + bytes([level & 0xFF])
    if not _write(ser, darkness_cmd, "setting printer darkness"):
        sys.exit(1)

    time.sleep(0.02)
    _read(ser)


def do_feed(ser, n_lines=None):
    if n_lines is None:
        n_lines = FEED

    # ESC d n is ignored by the tested printer, so feed with newline bytes.
    scroll = "\n" * n_lines
    if not _write(ser, scroll.encode(), "feeding paper"):
        sys.exit(1)


def print_raster(ser, payload):
    for _ in range(max(1, REPEAT)):
        _send(ser, payload)
        time.sleep(0.05)


def print_raster_image(ser, img: Image.Image):
    commands = list(img_to_escpos_raster_bands(img))
    for _ in range(max(1, REPEAT)):
        for payload in commands:
            _send(
                ser,
                payload,
                chunk=RASTER_CHUNK_SIZE,
                pause=RASTER_CHUNK_PAUSE,
            )
            time.sleep(RASTER_BAND_PAUSE)
        time.sleep(RASTER_JOB_PAUSE)


def prepare_raster_image(img: Image.Image) -> Image.Image:
    """Return a 1-bit image resized or centered to the printer width."""
    if img.mode != "1":
        img = img.convert("L")
        img = img.point(lambda x: 0 if x < 128 else 255, "1")

    if img.width > PRN_WIDTH:
        new_height = int(img.height * PRN_WIDTH / img.width)
        img = img.resize((PRN_WIDTH, new_height), Image.LANCZOS)

    if img.width < PRN_WIDTH:
        left_pad = (PRN_WIDTH - img.width) // 2
        canvas = Image.new("1", (PRN_WIDTH, img.height), 1)
        canvas.paste(img, (left_pad, 0))
        img = canvas

    return img


def pad_or_crop_to_printer_width(img: Image.Image) -> Image.Image:
    if img.width == PRN_WIDTH:
        return img

    if img.width > PRN_WIDTH:
        left = (img.width - PRN_WIDTH) // 2
        return img.crop((left, 0, left + PRN_WIDTH, img.height))

    left_pad = (PRN_WIDTH - img.width) // 2
    canvas = Image.new(img.mode, (PRN_WIDTH, img.height), _white_for_mode(img.mode))
    canvas.paste(img, (left_pad, 0))
    return canvas


def img_to_escpos_raster(img: Image.Image) -> bytes:
    img = prepare_raster_image(img)
    return _prepared_img_to_escpos_raster(img)


def img_to_escpos_raster_bands(
    img: Image.Image,
    band_height: int = RASTER_BAND_HEIGHT,
):
    img = prepare_raster_image(img)
    band_height = max(1, band_height)
    for top in range(0, img.height, band_height):
        bottom = min(top + band_height, img.height)
        band = img.crop((0, top, img.width, bottom))
        yield _prepared_img_to_escpos_raster(band)


def _prepared_img_to_escpos_raster(img: Image.Image) -> bytes:
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

    # GS v 0 m=0, xL xH yL yH: print raster image.
    cmd = b"\x1D\x76\x30\x00"
    cmd += bytes([
        x_bytes & 0xFF,
        (x_bytes >> 8) & 0xFF,
        img.height & 0xFF,
        (img.height >> 8) & 0xFF,
    ])
    cmd += data
    return cmd


def preprocess(img, invert=False, threshold=None):
    """Preprocess an image before converting it to 1-bit."""
    if img.mode != "L":
        img = img.convert("L")

    if BRIGHTNESS != 1.0:
        img = ImageEnhance.Brightness(img).enhance(BRIGHTNESS)
    if CONTRAST != 1.0:
        img = ImageEnhance.Contrast(img).enhance(CONTRAST)
    if GAMMA != 1.0:
        lut = [
            min(255, int(((i / 255.0) ** (1.0 / GAMMA)) * 255 + 0.5))
            for i in range(256)
        ]
        img = img.point(lut, mode="L")

    if invert:
        img = ImageOps.invert(img)

    if threshold is not None:
        return img.point(lambda x: 0 if x < threshold else 255, "1")

    if METHOD == "fs":
        img = img.convert("1")
    elif METHOD == "ordered":
        img = img.convert("1", dither=Image.Dither.NONE)
        img = ImageOps.posterize(img.convert("L"), 1).convert("1")
    else:
        img = img.point(lambda x: 0 if x < 128 else 255, "1")

    return img


def apply_image_geometry(img):
    img, selected_rotate = apply_image_rotation(img)
    img = apply_image_crop(img)

    fit_mode = IMAGE_FIT
    autofit_message = None
    if IMAGE_FIT == "autofit":
        fit_mode = choose_autofit_mode(img)
        autofit_message = f"autofit: rotate={selected_rotate}, fit={fit_mode}"
        if IMAGE_HEIGHT is not None:
            autofit_message += f", height={IMAGE_HEIGHT}"

    img = apply_image_fit(img, fit_mode)

    if autofit_message:
        print(autofit_message)

    return img


def apply_image_rotation(img):
    rotate = IMAGE_ROTATE
    if IMAGE_FIT == "autofit" and not IMAGE_ROTATE_EXPLICIT and _is_landscape(img):
        rotate = 90

    if rotate:
        img = rotate_image(img, rotate)

    return img, rotate


def rotate_image(img, degrees):
    rotations = {
        0: None,
        90: Image.Transpose.ROTATE_270,
        180: Image.Transpose.ROTATE_180,
        270: Image.Transpose.ROTATE_90,
    }
    transpose = rotations[degrees]
    return img if transpose is None else img.transpose(transpose)


def apply_image_crop(img):
    if IMAGE_CROP is None:
        return img

    left, top, width, height = IMAGE_CROP
    right = left + width
    bottom = top + height
    if right > img.width or bottom > img.height:
        print(
            f"[e] Crop {left},{top},{width},{height} exceeds image bounds "
            f"{img.width}x{img.height}"
        )
        sys.exit(1)

    return img.crop((left, top, right, bottom))


def choose_autofit_mode(img):
    if IMAGE_HEIGHT is None:
        return "width"

    target_ratio = PRN_WIDTH / IMAGE_HEIGHT
    source_ratio = img.width / img.height

    visible_fraction = min(source_ratio / target_ratio, target_ratio / source_ratio)
    aspect_loss = max(0.0, 1.0 - visible_fraction)
    return "cover" if aspect_loss <= 0.15 else "contain"


def apply_image_fit(img, fit_mode):
    if fit_mode == "width":
        return resize_to_width(img, PRN_WIDTH)
    if fit_mode == "none":
        return pad_or_crop_to_printer_width(img)
    if fit_mode == "stretch":
        require_image_height(fit_mode)
        return img.resize((PRN_WIDTH, IMAGE_HEIGHT), Image.LANCZOS)
    if fit_mode == "contain":
        require_image_height(fit_mode)
        return contain_image(img, PRN_WIDTH, IMAGE_HEIGHT)
    if fit_mode == "cover":
        require_image_height(fit_mode)
        return cover_image(img, PRN_WIDTH, IMAGE_HEIGHT, IMAGE_CROP_ALIGN)

    print(f"[e] Unsupported fit mode: {fit_mode}")
    sys.exit(1)


def resize_to_width(img, target_width):
    if img.width == target_width:
        return img

    target_height = max(1, round(img.height * target_width / img.width))
    return img.resize((target_width, target_height), Image.LANCZOS)


def contain_image(img, target_width, target_height):
    scale = min(target_width / img.width, target_height / img.height)
    new_size = (
        max(1, round(img.width * scale)),
        max(1, round(img.height * scale)),
    )
    resized = img.resize(new_size, Image.LANCZOS)
    canvas = Image.new(img.mode, (target_width, target_height), _white_for_mode(img.mode))
    canvas.paste(
        resized,
        ((target_width - resized.width) // 2, (target_height - resized.height) // 2),
    )
    return canvas


def cover_image(img, target_width, target_height, crop_align):
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


def require_image_height(fit_mode):
    if IMAGE_HEIGHT is None:
        print(f"[e] --height is required when --fit {fit_mode} is used")
        sys.exit(1)


def _white_for_mode(mode):
    if mode == "1":
        return 1
    if mode == "L":
        return 255
    return "white"


def _is_landscape(img):
    return img.width > img.height * 1.1


def apply_text_density(img):
    if TEXT_DENSITY == "normal":
        return img

    if img.mode != "1":
        img = img.convert("1")
    img = img.convert("L")

    if TEXT_DENSITY == "light":
        px = img.load()
        for y in range(img.height):
            for x in range(img.width):
                if px[x, y] == 0 and (x + y) % 3 == 0:
                    px[x, y] = 255
        return img.convert("1", dither=Image.Dither.NONE)

    if TEXT_DENSITY == "dark":
        img = img.filter(ImageFilter.MinFilter(3))
        return img.point(lambda x: 0 if x < 255 else 255, "1")

    return img.convert("1", dither=Image.Dither.NONE)


def wrap_text_to_width(text, font, max_w):
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


def load_image(path):
    try:
        with Image.open(path) as img:
            return ImageOps.exif_transpose(img).copy()
    except FileNotFoundError:
        print(f"[e] Image file not found: {path}")
    except Image.UnidentifiedImageError as e:
        print(f"[e] Cannot read image file: {path}: {e}")
    except OSError as e:
        print(f"[e] Cannot read image file: {path}: {e}")

    sys.exit(1)


def print_png(path):
    require_pillow_dependency()

    img = load_image(path)
    img = apply_image_geometry(img)
    img = preprocess(img, invert=IMAGE_INVERT, threshold=THRESHOLD)

    if IS_PREVIEW:
        img.save("debug.png")
        return

    with open_printer() as ser:
        escpos_init(ser)
        print_raster_image(ser, img)
        do_feed(ser, n_lines=FEED)


def render_text_image(text):
    require_pillow_dependency()

    font = load_font(FONT_PATH)
    text = text.replace("\\n", "\n").replace("\\t", "\t")
    lines = wrap_text_to_width(text, font, PRN_WIDTH)

    font_height = get_font_height(font)
    line_heights = [font_height for _ in lines]
    total_height = sum(line_heights)

    line_spacing_px = FONT_SIZE * LINE_SPACING
    if len(lines) > 1:
        total_height += line_spacing_px * (len(lines) - 1)

    img = Image.new("L", (PRN_WIDTH, int(total_height + PAD_Y * 2)), 255)
    draw = ImageDraw.Draw(img)

    y_offset = PAD_Y
    for i, line in enumerate(lines):
        line = line.replace("\t", "    ")
        if line.strip():
            bbox = font.getbbox(line)
            text_w = bbox[2] - bbox[0]

            if ALIGNMENT == "center":
                x = (PRN_WIDTH - text_w) // 2
            elif ALIGNMENT == "right":
                x = PRN_WIDTH - text_w
            else:
                x = 0

            draw.text((max(0, x), int(y_offset)), line, font=font, fill=0)

        y_offset += line_heights[i]
        if i < len(lines) - 1:
            y_offset += line_spacing_px

    return img


def print_text(text):
    img = render_text_image(text)
    img = preprocess(img)
    img = apply_text_density(img)

    if IS_PREVIEW:
        img.save("debug.png")
        return

    with open_printer() as ser:
        escpos_init(ser)
        print_raster_image(ser, img)
        do_feed(ser, n_lines=FEED)


def positive_int(value):
    ivalue = int(value)
    if ivalue <= 0:
        raise argparse.ArgumentTypeError("must be greater than 0")
    return ivalue


def non_negative_int(value):
    ivalue = int(value)
    if ivalue < 0:
        raise argparse.ArgumentTypeError("must be 0 or greater")
    return ivalue


def positive_float(value):
    fvalue = float(value)
    if fvalue <= 0:
        raise argparse.ArgumentTypeError("must be greater than 0")
    return fvalue


def non_negative_float(value):
    fvalue = float(value)
    if fvalue < 0:
        raise argparse.ArgumentTypeError("must be 0 or greater")
    return fvalue


def threshold_int(value):
    ivalue = int(value)
    if ivalue < 0 or ivalue > 255:
        raise argparse.ArgumentTypeError("must be between 0 and 255")
    return ivalue


def parse_crop(value):
    parts = value.split(",")
    if len(parts) != 4:
        raise argparse.ArgumentTypeError("must be left,top,width,height")

    try:
        left, top, width, height = [int(part) for part in parts]
    except ValueError as e:
        raise argparse.ArgumentTypeError("crop values must be integers") from e

    if left < 0 or top < 0:
        raise argparse.ArgumentTypeError("left and top must be 0 or greater")
    if width <= 0 or height <= 0:
        raise argparse.ArgumentTypeError("width and height must be greater than 0")

    return (left, top, width, height)


def apply_runtime_config(config):
    global PORT, RFCOMM_SERVICE, BAUDRATE, PRN_WIDTH, DPI, FONT_PATH
    global FONT_SIZE, PAD_Y, LINE_SPACING, ALIGNMENT
    global BRIGHTNESS, CONTRAST, GAMMA, METHOD, TEXT_DENSITY
    global FEED, REPEAT, IS_PREVIEW
    global IMAGE_ROTATE, IMAGE_ROTATE_EXPLICIT, IMAGE_CROP, IMAGE_FIT
    global IMAGE_HEIGHT, IMAGE_CROP_ALIGN, IMAGE_INVERT, THRESHOLD

    device = config["device"]
    printer = config["printer"]
    text = config["text"]
    image = config["image"]

    PORT = device["port"]
    RFCOMM_SERVICE = device["rfcommService"]
    BAUDRATE = device["baudrate"]
    PRN_WIDTH = printer["width"]
    DPI = PRN_WIDTH
    FONT_PATH = text["font"]

    FONT_SIZE = text["fontSize"]
    PAD_Y = text["padY"]
    LINE_SPACING = text["lineSpacing"]
    ALIGNMENT = text["align"]
    TEXT_DENSITY = text["density"]

    BRIGHTNESS = image["brightness"]
    CONTRAST = image["contrast"]
    GAMMA = image["gamma"]
    METHOD = image["method"]
    IMAGE_ROTATE = image["rotate"]
    IMAGE_ROTATE_EXPLICIT = image["rotate"] != DEFAULT_CONFIG["image"]["rotate"]
    IMAGE_CROP = None
    IMAGE_FIT = image["fit"]
    IMAGE_HEIGHT = image["height"]
    IMAGE_CROP_ALIGN = image["cropAlign"]
    IMAGE_INVERT = image["invert"]
    THRESHOLD = image["threshold"]

    FEED = printer["feed"]
    REPEAT = printer["repeat"]
    IS_PREVIEW = False


def apply_cli_overrides(args):
    global FONT_SIZE, PAD_Y, ALIGNMENT, BRIGHTNESS, CONTRAST, GAMMA, METHOD
    global TEXT_DENSITY, FEED, REPEAT, IS_PREVIEW, LINE_SPACING
    global IMAGE_ROTATE, IMAGE_ROTATE_EXPLICIT, IMAGE_CROP, IMAGE_FIT
    global IMAGE_HEIGHT, IMAGE_CROP_ALIGN, IMAGE_INVERT, THRESHOLD

    if hasattr(args, "brightness"):
        BRIGHTNESS = args.brightness
    if hasattr(args, "contrast"):
        CONTRAST = args.contrast
    if hasattr(args, "gamma"):
        GAMMA = args.gamma
    if hasattr(args, "method"):
        METHOD = args.method
    if hasattr(args, "feed"):
        FEED = args.feed
    if hasattr(args, "repeat"):
        REPEAT = args.repeat
    if hasattr(args, "preview"):
        IS_PREVIEW = args.preview

    if args.cmd == "img":
        if hasattr(args, "rotate"):
            IMAGE_ROTATE = args.rotate
            IMAGE_ROTATE_EXPLICIT = True
        if hasattr(args, "crop"):
            IMAGE_CROP = args.crop
        if hasattr(args, "fit"):
            IMAGE_FIT = args.fit
        if hasattr(args, "height"):
            IMAGE_HEIGHT = args.height
        if hasattr(args, "crop_align"):
            IMAGE_CROP_ALIGN = args.crop_align
        if hasattr(args, "invert"):
            IMAGE_INVERT = args.invert
        if hasattr(args, "threshold"):
            THRESHOLD = args.threshold

    if args.cmd == "text":
        if hasattr(args, "size"):
            FONT_SIZE = args.size
        if hasattr(args, "pad_y"):
            PAD_Y = args.pad_y
        if hasattr(args, "line_spacing"):
            LINE_SPACING = args.line_spacing
        if hasattr(args, "align"):
            ALIGNMENT = args.align
        if hasattr(args, "text_density"):
            TEXT_DENSITY = args.text_density


def apply_preset_defaults(args):
    if not hasattr(args, "preset"):
        return

    presets = TEXT_PRESETS if args.cmd == "text" else IMAGE_PRESETS
    apply_option_defaults(presets[args.preset])


def apply_option_defaults(defaults):
    global BRIGHTNESS, CONTRAST, GAMMA, METHOD, TEXT_DENSITY
    global IMAGE_FIT, THRESHOLD

    if "brightness" in defaults:
        BRIGHTNESS = defaults["brightness"]
    if "contrast" in defaults:
        CONTRAST = defaults["contrast"]
    if "gamma" in defaults:
        GAMMA = defaults["gamma"]
    if "method" in defaults:
        METHOD = defaults["method"]
    if "fit" in defaults:
        IMAGE_FIT = defaults["fit"]
    if "threshold" in defaults:
        THRESHOLD = defaults["threshold"]
    if "textDensity" in defaults:
        TEXT_DENSITY = defaults["textDensity"]


def add_render_args(parser):
    parser.add_argument(
        "-m",
        "--method",
        choices=["fs", "ordered", "th"],
        default=argparse.SUPPRESS,
        help="Dithering method (Floyd-Steinberg), (ordered), (hard threshold)",
    )
    parser.add_argument(
        "-b",
        "--brightness",
        type=positive_float,
        default=argparse.SUPPRESS,
        help="Brightness adjustment",
    )
    parser.add_argument(
        "-c",
        "--contrast",
        type=positive_float,
        default=argparse.SUPPRESS,
        help="Contrast adjustment",
    )
    parser.add_argument(
        "-g",
        "--gamma",
        type=positive_float,
        default=argparse.SUPPRESS,
        help="Gamma correction",
    )


def add_print_args(parser):
    parser.add_argument(
        "--feed",
        type=non_negative_int,
        default=argparse.SUPPRESS,
        help="Number of lines to feed",
    )
    parser.add_argument(
        "--repeat",
        type=positive_int,
        default=argparse.SUPPRESS,
        help="Number of times to repeat the text/image",
    )
    parser.add_argument(
        "--preview",
        action="store_true",
        help="Enable preview mode (save image to debug.png before printing)",
    )


def parse_args(prog=None):
    parser = argparse.ArgumentParser(prog=prog)
    parser.add_argument(
        "--version",
        action="version",
        version=f"kotPrinter {__version__}",
    )
    parser.add_argument(
        "--config",
        metavar="PATH",
        help=f"Path to JSON config (default: {DEFAULT_CONFIG_NAME} when present)",
    )
    subparsers = parser.add_subparsers(dest="cmd", required=True)

    text_parser = subparsers.add_parser("text")
    text_parser.add_argument("text")
    text_parser.add_argument(
        "--preset",
        choices=["text", "label"],
        default=argparse.SUPPRESS,
        help="Apply named defaults before explicit text options",
    )
    text_parser.add_argument(
        "-s",
        "--size",
        type=positive_int,
        default=argparse.SUPPRESS,
        help="Font size in pixels",
    )
    text_parser.add_argument(
        "-a",
        "--align",
        choices=["left", "center", "right"],
        default=argparse.SUPPRESS,
        help="Horizontal text alignment",
    )
    text_parser.add_argument(
        "-p",
        "--pad_y",
        type=non_negative_int,
        default=argparse.SUPPRESS,
        help="Padding on top and bottom of text in pixels",
    )
    text_parser.add_argument(
        "-l",
        "--line_spacing",
        type=non_negative_float,
        default=argparse.SUPPRESS,
        help="Line spacing coefficient from font size",
    )
    text_parser.add_argument(
        "--text-density",
        choices=["light", "normal", "dark"],
        default=argparse.SUPPRESS,
        help="Text raster density",
    )

    img_parser = subparsers.add_parser("img")
    img_parser.add_argument("path", help="Path to the image file")
    img_parser.add_argument(
        "--preset",
        choices=["text", "label", "photo", "sticker"],
        default=argparse.SUPPRESS,
        help="Apply named defaults before explicit image options",
    )
    img_parser.add_argument(
        "--rotate",
        type=int,
        choices=[0, 90, 180, 270],
        default=argparse.SUPPRESS,
        help="Rotate image clockwise before fitting",
    )
    img_parser.add_argument(
        "--crop",
        type=parse_crop,
        default=argparse.SUPPRESS,
        help="Crop before fitting as left,top,width,height",
    )
    img_parser.add_argument(
        "--fit",
        choices=["width", "contain", "cover", "stretch", "none", "autofit"],
        default=argparse.SUPPRESS,
        help="Map image to printer width",
    )
    img_parser.add_argument(
        "--height",
        type=positive_int,
        default=argparse.SUPPRESS,
        help="Target height for contain, cover, stretch, and autofit",
    )
    img_parser.add_argument(
        "--crop-align",
        choices=["top", "center", "bottom"],
        default=argparse.SUPPRESS,
        help="Vertical crop alignment for cover fit",
    )
    img_parser.add_argument(
        "--invert",
        action="store_true",
        default=argparse.SUPPRESS,
        help="Invert black and white before 1-bit conversion",
    )
    img_parser.add_argument(
        "--threshold",
        type=threshold_int,
        default=argparse.SUPPRESS,
        help="Use exact 0..255 threshold instead of dithering",
    )

    subparsers.add_parser("info")

    check_parser = subparsers.add_parser("check")
    check_parser.add_argument(
        "--live",
        action="store_true",
        help="Contact the printer with a wake/info handshake without printing",
    )

    install_parser = subparsers.add_parser("install")
    install_parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Show planned system changes without modifying the machine",
    )

    for subparser in (text_parser, img_parser):
        add_render_args(subparser)
        add_print_args(subparser)

    return parser


def main(argv=None, prog=None):
    parser = parse_args(prog=prog)
    args = parser.parse_args(argv)

    try:
        loaded_config = load_config(args.config)
    except ConfigError as e:
        parser.error(str(e))

    apply_runtime_config(loaded_config.data)

    if args.cmd == "check":
        results = run_checks(
            loaded_config.data,
            config_path=loaded_config.path,
            config_warnings=loaded_config.warnings,
            live=args.live,
        )
        print_check_report(results)
        return check_exit_code(results)

    for warning in loaded_config.warnings:
        print(f"[w] {warning}", file=sys.stderr)

    if args.cmd == "install":
        try:
            return run_install(loaded_config.data, dry_run=args.dry_run)
        except InstallError as e:
            print(f"[e] {e}")
            return 1

    if args.cmd == "info":
        with open_printer(quiet=True) as ser:
            get_printer_info(ser)
        return 0

    apply_preset_defaults(args)
    apply_cli_overrides(args)

    if args.cmd == "text":
        print_text(args.text)
    elif args.cmd == "img":
        print_png(args.path)
    else:
        print(f"[e] Unknown command: {args.cmd}")
        print("Use 'info', 'text', or 'img' command")
        return 0


if __name__ == "__main__":
    raise SystemExit(main())
