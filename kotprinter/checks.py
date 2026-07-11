import getpass
import grp
import importlib
import os
import shutil
import stat
import subprocess
import termios
import time
from dataclasses import asdict, dataclass
from importlib import metadata
from typing import List


OK = "OK"
WARN = "WARN"
FAIL = "FAIL"

HANDSHAKE = [
    b"\x1E\x47\x03",
    b"\x1D\x67\x39",
]


@dataclass
class CheckResult:
    name: str
    status: str
    message: str
    action: str = ""

    def as_dict(self):
        return asdict(self)


def run_checks(config, config_path=None, config_warnings=None, live=False):
    results = []
    config_warnings = config_warnings or []

    results.extend(_check_config(config, config_path, config_warnings))
    results.extend(_check_python_dependencies())
    results.append(_check_command_available("rfcomm", "RFCOMM tool"))
    results.extend(_check_bluetooth())
    results.extend(_check_systemd_unit(config["device"]["rfcommService"]))
    results.extend(_check_rfcomm_device(config["device"]["port"]))
    results.extend(_check_current_user(config["device"]["port"]))

    if live:
        results.append(_check_printer_live(config))

    return results


def print_check_report(results):
    print("KotPrinter environment check")
    print()

    name_width = max((len(result.name) for result in results), default=0)
    for result in results:
        print(f"{result.status:<4} {result.name:<{name_width}} {result.message}")
        if result.action:
            print(f"     next: {result.action}")


def check_exit_code(results):
    return 1 if any(result.status == FAIL for result in results) else 0


def _check_config(config, config_path, warnings):
    source = config_path or "built-in defaults"
    device = config["device"]
    printer = config["printer"]
    results = [
        CheckResult(
            "Configuration",
            OK,
            f"using {source}",
        ),
        CheckResult(
            "Printer config",
            OK,
            (
                f"{device['name']} at {device['mac']} channel {device['channel']}, "
                f"{printer['width']} dots wide"
            ),
        ),
    ]
    for warning in warnings:
        results.append(CheckResult("Config warning", WARN, warning))
    return results


def _check_python_dependencies():
    return [
        _check_python_package("Pillow", "PIL", "Python dependency: Pillow"),
        _check_python_package("pyserial", "serial", "Python dependency: pyserial"),
    ]


def _check_python_package(distribution_name, module_name, display_name):
    try:
        importlib.import_module(module_name)
    except ImportError:
        return CheckResult(
            display_name,
            FAIL,
            "not installed",
            f'install with `python3 -m pip install "{distribution_name}"`',
        )

    try:
        version = metadata.version(distribution_name)
    except metadata.PackageNotFoundError:
        version = "installed, version unknown"

    return CheckResult(display_name, OK, str(version))


def _check_command_available(command, display_name):
    path = shutil.which(command)
    if path:
        return CheckResult(display_name, OK, path)
    return CheckResult(
        display_name,
        FAIL,
        f"`{command}` not found",
        "install BlueZ tools, usually with `sudo apt install bluez`",
    )


def _check_bluetooth():
    results = []
    systemctl = shutil.which("systemctl")
    bluetoothctl = shutil.which("bluetoothctl")

    if systemctl:
        active = _run_command(["systemctl", "is-active", "bluetooth.service"])
        state = active.stdout.strip() or active.stderr.strip() or "unknown"
        if active.returncode == 0 and state == "active":
            results.append(CheckResult("Bluetooth service", OK, "active"))
        elif state == "failed":
            results.append(
                CheckResult(
                    "Bluetooth service",
                    FAIL,
                    "failed",
                    "run `systemctl status bluetooth.service --no-pager`",
                )
            )
        else:
            results.append(
                CheckResult(
                    "Bluetooth service",
                    WARN,
                    state,
                    "run `sudo systemctl start bluetooth.service` if Bluetooth is needed",
                )
            )
    else:
        results.append(
            CheckResult("Bluetooth service", WARN, "`systemctl` not found")
        )

    if not bluetoothctl:
        results.append(
            CheckResult(
                "Bluetooth controller",
                FAIL,
                "`bluetoothctl` not found",
                "install BlueZ tools, usually with `sudo apt install bluez`",
            )
        )
        return results

    show = _run_command(["bluetoothctl", "show"])
    output = (show.stdout + "\n" + show.stderr).strip()
    if show.returncode != 0 or "No default controller available" in output:
        results.append(
            CheckResult(
                "Bluetooth controller",
                FAIL,
                "no default controller available",
                "check the Bluetooth adapter and `bluetoothctl show`",
            )
        )
        return results

    powered = _find_bluetooth_field(output, "Powered")
    controller = _find_bluetooth_field(output, "Name") or "default controller"
    if powered == "yes":
        results.append(CheckResult("Bluetooth controller", OK, f"{controller}, powered"))
    elif powered == "no":
        results.append(
            CheckResult(
                "Bluetooth controller",
                FAIL,
                f"{controller}, powered off",
                "run `bluetoothctl power on`",
            )
        )
    else:
        results.append(
            CheckResult(
                "Bluetooth controller",
                WARN,
                f"{controller}, powered state unknown",
                "run `bluetoothctl show`",
            )
        )

    return results


def _find_bluetooth_field(output, field):
    prefix = f"{field}:"
    for line in output.splitlines():
        line = line.strip()
        if line.startswith(prefix):
            return line.split(":", 1)[1].strip()
    return None


def _check_systemd_unit(service_name):
    results = []
    unit_path = os.path.join("/etc/systemd/system", service_name)
    if os.path.exists(unit_path):
        results.append(CheckResult("Systemd unit file", OK, unit_path))
    else:
        results.append(
            CheckResult(
                "Systemd unit file",
                FAIL,
                f"{unit_path} not found",
                "run `python3 print.py install --dry-run`, then `python3 print.py install`",
            )
        )

    if not shutil.which("systemctl"):
        results.append(
            CheckResult("Systemd unit state", WARN, "`systemctl` not found")
        )
        return results

    enabled = _run_command(["systemctl", "is-enabled", service_name])
    enabled_state = enabled.stdout.strip() or enabled.stderr.strip() or "unknown"
    if enabled.returncode == 0 and enabled_state == "enabled":
        results.append(CheckResult("Systemd unit enabled", OK, "enabled"))
    else:
        results.append(
            CheckResult(
                "Systemd unit enabled",
                WARN,
                enabled_state,
                f"run `sudo systemctl enable {service_name}`",
            )
        )

    active = _run_command(["systemctl", "is-active", service_name])
    active_state = active.stdout.strip() or active.stderr.strip() or "unknown"
    if active.returncode == 0 and active_state == "active":
        results.append(CheckResult("Systemd unit active", OK, "active"))
    elif active_state == "failed":
        results.append(
            CheckResult(
                "Systemd unit active",
                FAIL,
                "failed",
                f"run `systemctl status {service_name} --no-pager`",
            )
        )
    else:
        results.append(
            CheckResult(
                "Systemd unit active",
                WARN,
                active_state,
                f"run `sudo systemctl restart {service_name}`",
            )
        )

    return results


def _check_rfcomm_device(port):
    if not os.path.exists(port):
        return [
            CheckResult(
                "RFCOMM device",
                FAIL,
                f"{port} does not exist",
                "restart the RFCOMM service after the printer is configured",
            )
        ]

    try:
        info = os.stat(port)
    except OSError as e:
        return [
            CheckResult(
                "RFCOMM device",
                FAIL,
                f"cannot stat {port}: {e}",
            )
        ]

    mode = stat.S_IMODE(info.st_mode)
    group = _group_name(info.st_gid)
    owner = _user_name(info.st_uid)
    access = (
        "read/write" if os.access(port, os.R_OK | os.W_OK) else "no read/write access"
    )
    status_value = OK if access == "read/write" else FAIL
    action = ""
    if status_value == FAIL:
        action = f"add the current user to `{group}` or fix permissions on {port}"

    return [
        CheckResult(
            "RFCOMM device",
            status_value,
            f"{port} {owner}:{group} {oct(mode)} ({access})",
            action,
        )
    ]


def _check_current_user(port):
    user = getpass.getuser()
    required_group = _required_serial_group(port)

    if required_group is None:
        return [
            CheckResult(
                "User serial group",
                WARN,
                f"cannot determine required group for {port}; assuming dialout",
                'run `groups "$USER"` and check access to the RFCOMM device',
            )
        ]

    if _user_in_group(required_group, user):
        return [
            CheckResult(
                "User serial group",
                OK,
                f"{user} is in {required_group}",
            )
        ]

    return [
        CheckResult(
            "User serial group",
            FAIL,
            f"{user} is not in {required_group}",
            (
                f"run `sudo usermod -aG {required_group} \"$USER\"`, "
                "then log out and back in"
            ),
        )
    ]


def _required_serial_group(port):
    if os.path.exists(port):
        try:
            return _group_name(os.stat(port).st_gid)
        except OSError:
            return None

    try:
        grp.getgrnam("dialout")
        return "dialout"
    except KeyError:
        return None


def _user_in_group(group_name, user):
    try:
        group = grp.getgrnam(group_name)
    except KeyError:
        return False

    group_ids = set(os.getgroups())
    return group.gr_gid in group_ids or user in group.gr_mem


def _check_printer_live(config):
    try:
        serial = importlib.import_module("serial")
    except ImportError:
        return CheckResult(
            "Printer live check",
            FAIL,
            "pyserial is not installed",
            'install with `python3 -m pip install "pyserial"`',
        )

    port = config["device"]["port"]
    baudrate = config["device"]["baudrate"]
    if not os.path.exists(port):
        return CheckResult(
            "Printer live check",
            WARN,
            f"{port} does not exist; cannot contact printer",
            "this may be an install/RFCOMM issue, not a printer power issue",
        )

    try:
        ser = serial.Serial(port, baudrate, timeout=0.7)
    except (OSError, serial.SerialException, termios.error) as e:
        message = str(e)
        status_value = FAIL if "Permission denied" in message else WARN
        action = "check serial permissions and group membership"
        if status_value == WARN:
            action = (
                "turn the printer on, close other clients, or restart the RFCOMM service"
            )
        return CheckResult(
            "Printer live check",
            status_value,
            f"cannot open {port}: {e}",
            action,
        )

    try:
        ser.write(HANDSHAKE[0])
        ser.flush()
        time.sleep(0.1)
        response = ser.read(256)
    except (OSError, serial.SerialException, termios.error) as e:
        return CheckResult(
            "Printer live check",
            WARN,
            f"handshake failed: {e}",
            "turn the printer on or power-cycle it, then retry",
        )
    finally:
        try:
            ser.close()
        except Exception:
            pass

    if not response:
        return CheckResult(
            "Printer live check",
            WARN,
            "printer did not answer wake/info handshake",
            "the printer may be asleep, off, busy, or out of range",
        )

    voltage = _extract_bytes_field(response, rb"VOLT=(\d+)mv")
    dpi = _extract_bytes_field(response, rb"DPI=(\d+)")
    details = "printer answered wake/info handshake"
    if voltage or dpi:
        details = f"{details}: VOLT={voltage or '?'}mV, DPI={dpi or '?'}"

    return CheckResult("Printer live check", OK, details)


def _extract_bytes_field(data, pattern):
    import re

    match = re.search(pattern, data, re.I)
    if not match:
        return None
    return match.group(1).decode(errors="replace")


def _run_command(args, timeout=3):
    try:
        return subprocess.run(
            args,
            check=False,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
            timeout=timeout,
        )
    except FileNotFoundError:
        return _MissingCommandResult(args[0])
    except subprocess.TimeoutExpired as e:
        return _TimeoutResult(args, e)


class _MissingCommandResult:
    def __init__(self, command):
        self.returncode = 127
        self.stdout = ""
        self.stderr = f"{command} not found"


class _TimeoutResult:
    def __init__(self, args, error):
        self.returncode = 124
        self.stdout = error.stdout or ""
        self.stderr = f"{' '.join(args)} timed out"


def _group_name(gid):
    try:
        return grp.getgrgid(gid).gr_name
    except KeyError:
        return str(gid)


def _user_name(uid):
    try:
        import pwd

        return pwd.getpwuid(uid).pw_name
    except (ImportError, KeyError):
        return str(uid)
