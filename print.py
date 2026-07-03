import argparse
import os
import re
import subprocess
import sys
import termios
import textwrap
import time

import serial
from PIL import Image, ImageDraw, ImageEnhance, ImageFilter, ImageFont, ImageOps


# Default RFCOMM device. Bind with: rfcomm bind /dev/rfcomm0 <MAC> 2
PORT = "/dev/rfcomm0"
RFCOMM_SERVICE = "rfcomm-printer.service"

PRN_WIDTH = 384
VOLT = 0
DPI = PRN_WIDTH
FONT_PATH = "/usr/share/fonts/truetype/dejavu/DejaVuSansMono.ttf"

FONT_SIZE = 20
PAD_Y = 6
LINE_SPACING = 0.5
ALIGNMENT = "left"
BRIGHTNESS = 1.0
CONTRAST = 1.0
GAMMA = 1.0
METHOD = "fs"
TEXT_DENSITY = "normal"
FEED = 5
REPEAT = 1
IS_PREVIEW = False

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
SERIAL_ERRORS = (OSError, serial.SerialException, termios.error)


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
            ser = serial.Serial(PORT, 115200, timeout=0.7)
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


def img_to_escpos_raster(img: Image.Image) -> bytes:
    img = prepare_raster_image(img)

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


def preprocess(img):
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

    if METHOD == "fs":
        img = img.convert("1")
    elif METHOD == "ordered":
        img = img.convert("1", dither=Image.Dither.NONE)
        img = ImageOps.posterize(img.convert("L"), 1).convert("1")
    else:
        img = img.point(lambda x: 0 if x < 128 else 255, "1")

    return img


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
            return img.copy()
    except FileNotFoundError:
        print(f"[e] Image file not found: {path}")
    except Image.UnidentifiedImageError as e:
        print(f"[e] Cannot read image file: {path}: {e}")
    except OSError as e:
        print(f"[e] Cannot read image file: {path}: {e}")

    sys.exit(1)


def print_png(path):
    img = load_image(path)
    img = preprocess(img)

    if IS_PREVIEW:
        img = prepare_raster_image(img)
        img.save("debug.png")
        return

    with open_printer() as ser:
        escpos_init(ser)
        payload = img_to_escpos_raster(img)
        print_raster(ser, payload)
        do_feed(ser, n_lines=FEED)


def render_text_image(text):
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
        payload = img_to_escpos_raster(img)
        print_raster(ser, payload)
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


def add_render_args(parser):
    parser.add_argument(
        "-m",
        "--method",
        choices=["fs", "ordered", "th"],
        default="fs",
        help="Dithering method (Floyd-Steinberg), (ordered), (hard threshold)",
    )
    parser.add_argument(
        "-b",
        "--brightness",
        type=positive_float,
        default=1.0,
        help="Brightness adjustment",
    )
    parser.add_argument(
        "-c",
        "--contrast",
        type=positive_float,
        default=1.0,
        help="Contrast adjustment",
    )
    parser.add_argument(
        "-g",
        "--gamma",
        type=positive_float,
        default=1.0,
        help="Gamma correction",
    )


def add_print_args(parser):
    parser.add_argument(
        "--feed",
        type=non_negative_int,
        default=5,
        help="Number of lines to feed",
    )
    parser.add_argument(
        "--repeat",
        type=positive_int,
        default=1,
        help="Number of times to repeat the text/image",
    )
    parser.add_argument(
        "--preview",
        action="store_true",
        help="Enable preview mode (save image to debug.png before printing)",
    )


def parse_args():
    parser = argparse.ArgumentParser()
    subparsers = parser.add_subparsers(dest="cmd", required=True)

    text_parser = subparsers.add_parser("text")
    text_parser.add_argument("text")
    text_parser.add_argument(
        "-s",
        "--size",
        type=positive_int,
        default=20,
        help="Font size in pixels",
    )
    text_parser.add_argument(
        "-a",
        "--align",
        choices=["left", "center", "right"],
        default="left",
        help="Horizontal text alignment",
    )
    text_parser.add_argument(
        "-p",
        "--pad_y",
        type=non_negative_int,
        default=6,
        help="Padding on top and bottom of text in pixels",
    )
    text_parser.add_argument(
        "-l",
        "--line_spacing",
        type=non_negative_float,
        default=0.5,
        help="Line spacing coefficient from font size",
    )
    text_parser.add_argument(
        "--text-density",
        choices=["light", "normal", "dark"],
        default="normal",
        help="Text raster density",
    )

    img_parser = subparsers.add_parser("img")
    img_parser.add_argument("path", help="Path to the image file")

    subparsers.add_parser("info")

    for subparser in (text_parser, img_parser):
        add_render_args(subparser)
        add_print_args(subparser)

    return parser


def main():
    global FONT_SIZE, PAD_Y, ALIGNMENT, BRIGHTNESS, CONTRAST, GAMMA, METHOD
    global TEXT_DENSITY, FEED, REPEAT, IS_PREVIEW, LINE_SPACING

    parser = parse_args()
    args = parser.parse_args()

    if args.cmd == "info":
        with open_printer(quiet=True) as ser:
            get_printer_info(ser)
        sys.exit(0)

    BRIGHTNESS = args.brightness
    CONTRAST = args.contrast
    GAMMA = args.gamma
    METHOD = args.method
    FEED = args.feed
    REPEAT = args.repeat
    IS_PREVIEW = args.preview

    if args.cmd == "text":
        FONT_SIZE = args.size
        PAD_Y = args.pad_y
        LINE_SPACING = args.line_spacing
        ALIGNMENT = args.align
        TEXT_DENSITY = args.text_density
        print_text(args.text)
    elif args.cmd == "img":
        print_png(args.path)
    else:
        print(f"[e] Unknown command: {args.cmd}")
        print("Use 'info', 'text', or 'img' command")
        sys.exit(0)


if __name__ == "__main__":
    main()
