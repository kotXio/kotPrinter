from __future__ import annotations

import os
import re
import subprocess
import termios
import threading
import time
from dataclasses import dataclass
from typing import Any, Callable, Optional

try:
    import serial
except ImportError:
    serial = None

from .core import PrintResult, RuntimeSettings
from .render import img_to_escpos_raster_bands


HANDSHAKE = [
    b"\x1E\x47\x03",
    b"\x1D\x67\x39",
]
SYSTEMCTL_BIN = "/usr/bin/systemctl"
RFCOMM_RECOVERY_COOLDOWN = 30.0
RFCOMM_RECOVERY_SETTLE_DELAY = 1.0
RFCOMM_RECOVERY_TIMEOUT = 15.0

SERIAL_ERRORS = (OSError, termios.error)
if serial is not None:
    SERIAL_ERRORS = SERIAL_ERRORS + (serial.SerialException,)


EventHandler = Optional[Callable[[str], None]]
_RFCOMM_RECOVERY_LOCK = threading.Lock()
_LAST_RFCOMM_RECOVERY_BY_SERVICE: dict[str, float] = {}


class TransportError(Exception):
    pass


class TransportDependencyError(TransportError):
    pass


class TransportOpenError(TransportError):
    pass


class TransportWriteError(TransportError):
    def __init__(self, message: str, *, partial: bool = False):
        super().__init__(message)
        self.partial = partial


@dataclass(frozen=True)
class PrinterStatus:
    voltage_mv: int = 0
    dpi: int = 0
    battery_percent: int = 0
    raw: bytes = b""


@dataclass(frozen=True)
class PrinterInfo:
    voltage_mv: int
    dpi: int
    battery_percent: int
    serial_number: str
    raw_info: bytes = b""
    raw_serial: bytes = b""


@dataclass(frozen=True)
class OpenedPrinter:
    serial: Any
    status: PrinterStatus


def emit(handler: EventHandler, message: str) -> None:
    if handler is not None:
        handler(message)


def require_serial_dependency() -> None:
    if serial is None:
        raise TransportDependencyError(
            "pyserial is not installed. Install it with "
            '`python3 -m pip install "pyserial"`.'
        )


def is_rfcomm_bound(settings: RuntimeSettings) -> bool:
    return os.path.exists(settings.device.port)


def _not_bound_error(settings: RuntimeSettings) -> TransportOpenError:
    port = settings.device.port
    service = settings.device.rfcomm_service
    return TransportOpenError(
        f"{port} is not bound. Run `python3 print.py install` once, "
        f"or ask an administrator to restart {service}."
    )


def recover_rfcomm_service(
    settings: RuntimeSettings,
    *,
    cooldown: float,
    settle_delay: float,
    on_event: EventHandler = None,
) -> bool:
    service = settings.device.rfcomm_service
    now = time.monotonic()

    with _RFCOMM_RECOVERY_LOCK:
        last_recovery = _LAST_RFCOMM_RECOVERY_BY_SERVICE.get(service)
        if last_recovery is not None and cooldown > 0:
            remaining = cooldown - (now - last_recovery)
            if remaining > 0:
                emit(
                    on_event,
                    (
                        "[w] Automatic RFCOMM recovery was attempted recently; "
                        f"retry in {remaining:.0f}s"
                    ),
                )
                return False
        _LAST_RFCOMM_RECOVERY_BY_SERVICE[service] = now

    command = ["sudo", "-n", SYSTEMCTL_BIN, "restart", service]
    emit(
        on_event,
        f"[w] Recovering RFCOMM with: sudo -n {SYSTEMCTL_BIN} restart {service}",
    )
    try:
        result = subprocess.run(
            command,
            check=False,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
            timeout=RFCOMM_RECOVERY_TIMEOUT,
        )
    except FileNotFoundError as e:
        raise TransportOpenError(
            "Automatic RFCOMM recovery needs sudo, but `sudo` was not found."
        ) from e
    except subprocess.TimeoutExpired as e:
        raise TransportOpenError("Automatic RFCOMM recovery timed out.") from e

    if result.returncode != 0:
        details = (result.stderr or result.stdout or "unknown error").strip()
        raise TransportOpenError(f"Automatic RFCOMM recovery failed: {details}")

    time.sleep(settle_delay)
    return True


def close_serial(ser) -> None:
    try:
        ser.close()
    except Exception:
        pass


def write_bytes(ser, data: bytes, action: str) -> int:
    try:
        written = ser.write(data)
        ser.flush()
        return len(data) if written is None else written
    except SERIAL_ERRORS as e:
        raise TransportWriteError(f"Error {action}: {e}") from e


def send_bytes(
    ser,
    data: bytes,
    *,
    chunk_size: int,
    chunk_pause: float,
) -> int:
    bytes_written = 0
    for i in range(0, len(data), chunk_size):
        chunk = data[i:i + chunk_size]
        try:
            written = ser.write(chunk)
            ser.flush()
            bytes_written += len(chunk) if written is None else written
            time.sleep(chunk_pause)
        except SERIAL_ERRORS as e:
            close_serial(ser)
            raise TransportWriteError(
                f"Error sending data to printer: {e}",
                partial=True,
            ) from e

    return bytes_written


def read_bytes(ser, size: int = 256) -> Optional[bytes]:
    try:
        response = ser.read(size)
        if response:
            return response
    except SERIAL_ERRORS as e:
        raise TransportError(f"Error reading from printer: {e}") from e

    return None


def get_battery_percent(voltage_mv: int) -> int:
    if voltage_mv >= 8000:
        return 100
    if voltage_mv <= 6800:
        return 0

    return int((voltage_mv - 6800) / (8000 - 6800) * 100)


def parse_printer_status(data: bytes, default_dpi: int) -> PrinterStatus:
    m_volt = re.search(rb"VOLT=(\d+)mv", data, re.I)
    m_dpi = re.search(rb"DPI=(\d+)", data, re.I)
    voltage_mv = int(m_volt.group(1)) if m_volt else 0
    dpi = int(m_dpi.group(1)) if m_dpi else default_dpi

    return PrinterStatus(
        voltage_mv=voltage_mv,
        dpi=dpi,
        battery_percent=get_battery_percent(voltage_mv),
        raw=data,
    )


def wake_printer(ser, settings: RuntimeSettings) -> Optional[PrinterStatus]:
    try:
        write_bytes(ser, HANDSHAKE[0], "sending wake handshake to printer")
        time.sleep(0.1)
        info = read_bytes(ser)
    except TransportError:
        return None

    if not info:
        return None

    return parse_printer_status(info, settings.printer.width)


def open_printer(
    settings: RuntimeSettings,
    *,
    retries: int,
    quiet: bool = False,
    wake_retry_delay: float,
    rfcomm_recovery: bool = True,
    rfcomm_recovery_cooldown: float = RFCOMM_RECOVERY_COOLDOWN,
    rfcomm_recovery_settle_delay: float = RFCOMM_RECOVERY_SETTLE_DELAY,
    on_event: EventHandler = None,
) -> OpenedPrinter:
    require_serial_dependency()

    try:
        return _open_printer_without_recovery(
            settings,
            retries=retries,
            quiet=quiet,
            wake_retry_delay=wake_retry_delay,
            on_event=on_event,
        )
    except TransportOpenError as first_error:
        if not rfcomm_recovery:
            raise

        emit(on_event, f"[w] {first_error}")
        try:
            recovered = recover_rfcomm_service(
                settings,
                cooldown=rfcomm_recovery_cooldown,
                settle_delay=rfcomm_recovery_settle_delay,
                on_event=on_event,
            )
        except TransportOpenError as recovery_error:
            raise TransportOpenError(
                f"{first_error} {recovery_error}"
            ) from recovery_error

        if not recovered:
            raise TransportOpenError(
                f"{first_error} Automatic RFCOMM recovery is in cooldown."
            ) from first_error

        try:
            return _open_printer_without_recovery(
                settings,
                retries=retries,
                quiet=quiet,
                wake_retry_delay=wake_retry_delay,
                on_event=on_event,
            )
        except TransportOpenError as second_error:
            raise TransportOpenError(
                f"{second_error} Automatic RFCOMM recovery already ran once "
                "for this request."
            ) from second_error


def _open_printer_without_recovery(
    settings: RuntimeSettings,
    *,
    retries: int,
    quiet: bool,
    wake_retry_delay: float,
    on_event: EventHandler = None,
) -> OpenedPrinter:
    last_error = None

    port = settings.device.port

    if not is_rfcomm_bound(settings):
        raise _not_bound_error(settings)

    for attempt in range(1, retries + 1):
        if not is_rfcomm_bound(settings):
            emit(on_event, f"[w] {port} disappeared before opening")
            time.sleep(wake_retry_delay)
            continue

        try:
            ser = serial.Serial(port, settings.device.baudrate, timeout=0.7)
        except SERIAL_ERRORS as e:
            last_error = e
            emit(on_event, f"[w] Cannot open {port} (attempt {attempt}/{retries}): {e}")
            time.sleep(wake_retry_delay)
            continue

        status = wake_printer(ser, settings)
        if status is not None:
            if not quiet:
                emit(
                    on_event,
                    (
                        f"[i] Printer awake: {status.voltage_mv}mV, "
                        f"DPI: {status.dpi}, Battery: {status.battery_percent}%"
                    ),
                )
            return OpenedPrinter(serial=ser, status=status)

        emit(
            on_event,
            f"[w] Printer did not answer wake handshake (attempt {attempt}/{retries})",
        )
        close_serial(ser)
        time.sleep(wake_retry_delay)

    if not is_rfcomm_bound(settings):
        raise _not_bound_error(settings)
    if last_error:
        raise TransportOpenError(f"Last serial error: {last_error}")

    raise TransportOpenError(
        "Printer did not answer. Try power-cycling it, then run the command again."
    )


def get_printer_info(ser, settings: RuntimeSettings) -> PrinterInfo:
    write_bytes(ser, HANDSHAKE[0], "sending printer-info request")
    time.sleep(0.05)
    info = read_bytes(ser)
    if not info:
        raise TransportError("No response from printer")

    status = parse_printer_status(info, settings.printer.width)

    write_bytes(ser, HANDSHAKE[1], "sending serial-number request")
    time.sleep(0.05)
    serial_number = read_bytes(ser)
    if not serial_number:
        raise TransportError("No response from printer for serial number")

    serial_text = serial_number.decode(errors="replace").rstrip("\x00").strip()
    return PrinterInfo(
        voltage_mv=status.voltage_mv,
        dpi=status.dpi,
        battery_percent=status.battery_percent,
        serial_number=serial_text,
        raw_info=info,
        raw_serial=serial_number,
    )


def initialize_printer(ser) -> PrintResult:
    written = write_bytes(ser, b"\x1B@", "initializing printer")
    time.sleep(0.02)
    try:
        read_bytes(ser)
    except TransportError:
        pass

    return PrintResult(success=True, bytes_written=written)


def send_density(ser, profile="med") -> PrintResult:
    presets = {
        "low": (20, 120, 30),
        "med": (32, 160, 30),
        "high": (48, 200, 40),
    }
    if isinstance(profile, tuple) and len(profile) == 3:
        n1, n2, n3 = profile
    else:
        n1, n2, n3 = presets.get(profile, presets["med"])

    bytes_written = 0
    density_cmd = b"\x1B\x37" + bytes([n1 & 0xFF, n2 & 0xFF, n3 & 0xFF])
    bytes_written += write_bytes(ser, density_cmd, "setting printer density")
    time.sleep(0.02)
    try:
        read_bytes(ser)
    except TransportError:
        pass

    level = 200 if profile == "high" else (150 if profile == "med" else 100)
    darkness_cmd = b"\x12\x23" + bytes([level & 0xFF])
    bytes_written += write_bytes(ser, darkness_cmd, "setting printer darkness")
    time.sleep(0.02)
    try:
        read_bytes(ser)
    except TransportError:
        pass

    return PrintResult(success=True, bytes_written=bytes_written)


def feed_paper(
    ser,
    settings: RuntimeSettings,
    n_lines: Optional[int] = None,
) -> PrintResult:
    if n_lines is None:
        n_lines = settings.printer.feed

    scroll = "\n" * n_lines
    written = write_bytes(ser, scroll.encode(), "feeding paper")
    return PrintResult(success=True, bytes_written=written)


def print_raster_image(
    ser,
    img,
    settings: RuntimeSettings,
    *,
    band_height: int,
    band_pause: float,
    chunk_size: int,
    chunk_pause: float,
    job_pause: float,
) -> PrintResult:
    commands = list(
        img_to_escpos_raster_bands(
            img,
            settings.printer.width,
            band_height,
        )
    )

    bytes_written = 0
    for _ in range(max(1, settings.printer.repeat)):
        for payload in commands:
            bytes_written += send_bytes(
                ser,
                payload,
                chunk_size=chunk_size,
                chunk_pause=chunk_pause,
            )
            time.sleep(band_pause)
        time.sleep(job_pause)

    return PrintResult(
        success=True,
        bytes_written=bytes_written,
        metadata={
            "bands": len(commands),
            "repeat": settings.printer.repeat,
            "bandHeight": band_height,
        },
    )
