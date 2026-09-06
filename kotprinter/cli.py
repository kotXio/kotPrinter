from __future__ import annotations

import argparse
import os
import sys

from . import __version__
from .checks import check_exit_code, print_check_report, run_checks
from .config import (
    ConfigError,
    DEFAULT_CONFIG,
    DEFAULT_CONFIG_NAME,
    get_project_config_path,
    load_config,
)
from .core import (
    IMAGE_PRESETS,
    ImageJob,
    TEXT_PRESETS,
    RuntimeSettings,
    TextJob,
    resolve_runtime_settings,
)
from .install import (
    DEFAULT_SERVER_HOST,
    DEFAULT_SERVER_PORT,
    DEFAULT_SERVER_SERVICE,
    InstallError,
    resolve_install_context,
    run_install,
)
from .render import (
    RenderError,
    render_image_job,
    render_text_job,
)
from .transport import (
    TransportError,
    TransportWriteError,
    feed_paper as transport_feed_paper,
    get_printer_info as transport_get_printer_info,
    initialize_printer,
    open_printer as transport_open_printer,
    print_raster_image as transport_print_raster_image,
    send_density,
)


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
CURRENT_SETTINGS = resolve_runtime_settings(
    DEFAULT_CONFIG,
    default_image_rotate=DEFAULT_CONFIG["image"]["rotate"],
)
RASTER_BAND_HEIGHT = 64
RASTER_BAND_PAUSE = 0.12
RASTER_CHUNK_SIZE = 128
RASTER_CHUNK_PAUSE = 0.03
RASTER_JOB_PAUSE = 0.4

WAKE_RETRIES = 3
WAKE_RETRY_DELAY = 1.0


def _exit_transport_error(error: TransportError):
    print(f"[e] {error}")
    if isinstance(error, TransportWriteError) and error.partial:
        print(
            "[e] The print may be partial. Check the printer, then retry "
            "or power-cycle it."
        )
    sys.exit(1)


def _update_printer_status(status):
    global VOLT, DPI
    VOLT = status.voltage_mv
    DPI = status.dpi


def open_printer(
    retries=WAKE_RETRIES,
    quiet=False,
):
    try:
        opened = transport_open_printer(
            CURRENT_SETTINGS,
            retries=retries,
            quiet=quiet,
            wake_retry_delay=WAKE_RETRY_DELAY,
            on_event=print,
        )
    except TransportError as e:
        _exit_transport_error(e)

    _update_printer_status(opened.status)
    return opened.serial


def get_printer_info(ser):
    try:
        info = transport_get_printer_info(ser, CURRENT_SETTINGS)
    except TransportError as e:
        _exit_transport_error(e)

    global VOLT, DPI
    VOLT = info.voltage_mv
    DPI = info.dpi

    print(
        f"[i] Printer voltage: {info.voltage_mv}mV, DPI: {info.dpi}, "
        f"Battery: {info.battery_percent}%"
    )
    print(f"[i] Printer serial number: {info.serial_number}")

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
    try:
        initialize_printer(ser)
    except TransportError as e:
        _exit_transport_error(e)


def set_density(ser, profile="med"):
    """Send experimental density commands. The tested printer ignores them."""
    try:
        send_density(ser, profile=profile)
    except TransportError as e:
        _exit_transport_error(e)


def do_feed(ser, n_lines=None):
    try:
        transport_feed_paper(ser, CURRENT_SETTINGS, n_lines=n_lines)
    except TransportError as e:
        _exit_transport_error(e)


def print_raster_image(ser, img):
    try:
        transport_print_raster_image(
            ser,
            img,
            CURRENT_SETTINGS,
            band_height=RASTER_BAND_HEIGHT,
            band_pause=RASTER_BAND_PAUSE,
            chunk_size=RASTER_CHUNK_SIZE,
            chunk_pause=RASTER_CHUNK_PAUSE,
            job_pause=RASTER_JOB_PAUSE,
        )
    except TransportError as e:
        _exit_transport_error(e)


def _render_or_exit(render_func, job):
    try:
        result = render_func(job)
    except RenderError as e:
        print(f"[e] {e}")
        sys.exit(1)

    for warning in result.warnings:
        print(warning)

    return result


def print_png(path):
    result = _render_or_exit(
        render_image_job,
        ImageJob(path=path, settings=CURRENT_SETTINGS),
    )
    img = result.image

    if IS_PREVIEW:
        img.save("debug.png")
        return

    with open_printer() as ser:
        escpos_init(ser)
        print_raster_image(ser, img)
        do_feed(ser, n_lines=FEED)


def print_text(text):
    result = _render_or_exit(
        render_text_job,
        TextJob(text=text, settings=CURRENT_SETTINGS),
    )
    img = result.image

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


def apply_runtime_settings(settings: RuntimeSettings):
    global CURRENT_SETTINGS
    global PORT, RFCOMM_SERVICE, BAUDRATE, PRN_WIDTH, DPI, FONT_PATH
    global FONT_SIZE, PAD_Y, LINE_SPACING, ALIGNMENT
    global BRIGHTNESS, CONTRAST, GAMMA, METHOD, TEXT_DENSITY
    global FEED, REPEAT, IS_PREVIEW
    global IMAGE_ROTATE, IMAGE_ROTATE_EXPLICIT, IMAGE_CROP, IMAGE_FIT
    global IMAGE_HEIGHT, IMAGE_CROP_ALIGN, IMAGE_INVERT, THRESHOLD

    CURRENT_SETTINGS = settings

    PORT = settings.device.port
    RFCOMM_SERVICE = settings.device.rfcomm_service
    BAUDRATE = settings.device.baudrate
    PRN_WIDTH = settings.printer.width
    DPI = PRN_WIDTH
    FONT_PATH = settings.text.font

    FONT_SIZE = settings.text.font_size
    PAD_Y = settings.text.pad_y
    LINE_SPACING = settings.text.line_spacing
    ALIGNMENT = settings.text.align
    TEXT_DENSITY = settings.text.density

    BRIGHTNESS = settings.render.brightness
    CONTRAST = settings.render.contrast
    GAMMA = settings.render.gamma
    METHOD = settings.render.method
    IMAGE_ROTATE = settings.image.rotate
    IMAGE_ROTATE_EXPLICIT = settings.image.rotate_explicit
    IMAGE_CROP = settings.image.crop
    IMAGE_FIT = settings.image.fit
    IMAGE_HEIGHT = settings.image.height
    IMAGE_CROP_ALIGN = settings.image.crop_align
    IMAGE_INVERT = settings.image.invert
    THRESHOLD = settings.image.threshold

    FEED = settings.printer.feed
    REPEAT = settings.printer.repeat
    IS_PREVIEW = settings.preview


def apply_runtime_config(config):
    settings = resolve_runtime_settings(
        config,
        default_image_rotate=DEFAULT_CONFIG["image"]["rotate"],
    )
    apply_runtime_settings(settings)


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
        choices=list(TEXT_PRESETS),
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
        choices=list(IMAGE_PRESETS),
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
    check_parser.add_argument(
        "--project-root",
        help="Project root used for web/dist and server checks",
    )
    check_parser.add_argument(
        "--server-port",
        type=positive_int,
        default=DEFAULT_SERVER_PORT,
        help="Expected KotPrinter server HTTP port",
    )
    check_parser.add_argument(
        "--server-service",
        default=DEFAULT_SERVER_SERVICE,
        help="Expected KotPrinter server systemd service name",
    )

    install_parser = subparsers.add_parser("install")
    install_parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Show planned system changes without modifying the machine",
    )
    install_parser.add_argument(
        "--project-root",
        help="Project root to render into the server systemd unit",
    )
    install_parser.add_argument(
        "--server-host",
        default=DEFAULT_SERVER_HOST,
        help="Host address for the installed KotPrinter server",
    )
    install_parser.add_argument(
        "--server-port",
        type=positive_int,
        default=DEFAULT_SERVER_PORT,
        help="HTTP port for the installed KotPrinter server",
    )
    install_parser.add_argument(
        "--server-service",
        default=DEFAULT_SERVER_SERVICE,
        help="Systemd service name for the installed KotPrinter server",
    )

    for subparser in (text_parser, img_parser):
        add_render_args(subparser)
        add_print_args(subparser)

    return parser


def main(argv=None, prog=None):
    parser = parse_args(prog=prog)
    args = parser.parse_args(argv)
    config_path = args.config
    if (
        config_path is None
        and args.cmd in {"check", "install"}
        and getattr(args, "project_root", None)
    ):
        project_config_path = get_project_config_path(args.project_root)
        if os.path.exists(project_config_path):
            config_path = project_config_path

    try:
        loaded_config = load_config(config_path)
    except ConfigError as e:
        parser.error(str(e))

    base_settings = resolve_runtime_settings(
        loaded_config.data,
        default_image_rotate=DEFAULT_CONFIG["image"]["rotate"],
    )
    apply_runtime_settings(base_settings)

    if args.cmd == "check":
        results = run_checks(
            loaded_config.data,
            config_path=loaded_config.path,
            config_warnings=loaded_config.warnings,
            live=args.live,
            project_root=args.project_root,
            server_port=args.server_port,
            server_service=args.server_service,
        )
        print_check_report(results)
        return check_exit_code(results)

    for warning in loaded_config.warnings:
        print(f"[w] {warning}", file=sys.stderr)

    if args.cmd == "install":
        try:
            context = resolve_install_context(
                project_root=args.project_root,
                config_path=loaded_config.path if args.config is not None else None,
                server_host=args.server_host,
                server_port=args.server_port,
                server_service=args.server_service,
            )
            return run_install(loaded_config.data, dry_run=args.dry_run, context=context)
        except InstallError as e:
            print(f"[e] {e}")
            return 1

    if args.cmd == "info":
        with open_printer(quiet=True) as ser:
            get_printer_info(ser)
        return 0

    runtime_settings = resolve_runtime_settings(
        loaded_config.data,
        command=args.cmd,
        preset=getattr(args, "preset", None),
        overrides=vars(args),
        default_image_rotate=DEFAULT_CONFIG["image"]["rotate"],
    )
    apply_runtime_settings(runtime_settings)

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
