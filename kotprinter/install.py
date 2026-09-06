import getpass
import grp
import os
import re
import subprocess
from dataclasses import dataclass
from pathlib import Path


SYSTEMD_DIR = "/etc/systemd/system"
SUDOERS_DIR = "/etc/sudoers.d"
SUDOERS_FILE = "kotprinter-rfcomm"
DEFAULT_SERVER_HOST = "0.0.0.0"
DEFAULT_SERVER_PORT = 8000
DEFAULT_SERVER_SERVICE = "kotprinter.service"
PYTHON_BIN = "/usr/bin/python3"
SYSTEMCTL_BIN = "/usr/bin/systemctl"
TEST_BIN = "/usr/bin/test"
VISUDO_BIN = "/usr/sbin/visudo"


class InstallError(Exception):
    pass


@dataclass(frozen=True)
class InstallContext:
    project_root: Path
    config_path: Path | None
    server_host: str
    server_port: int
    server_service: str
    server_user: str


def run_install(config, dry_run=False, context=None):
    plan = build_install_plan(config, context=context)
    if dry_run:
        print_install_plan(plan)
        return 0

    apply_install_plan(plan)
    return 0


def resolve_install_context(
    *,
    project_root=None,
    config_path=None,
    server_host=DEFAULT_SERVER_HOST,
    server_port=DEFAULT_SERVER_PORT,
    server_service=DEFAULT_SERVER_SERVICE,
    server_user=None,
):
    root = Path(project_root).expanduser().resolve() if project_root else Path.cwd()
    root = root.resolve()
    _validate_project_root(root)

    resolved_config = (
        Path(config_path).expanduser().resolve()
        if config_path is not None
        else None
    )
    _require_systemd_service_name(server_service, "server service")
    _validate_server_host(server_host)
    _validate_server_port(server_port)
    resolved_user = server_user or getpass.getuser()
    _validate_server_user(resolved_user)

    return InstallContext(
        project_root=root,
        config_path=resolved_config,
        server_host=server_host,
        server_port=server_port,
        server_service=server_service,
        server_user=resolved_user,
    )


def build_install_plan(config, context=None):
    context = context or resolve_install_context()
    rfcomm_service_name = config["device"]["rfcommService"]
    server_service_name = context.server_service
    if rfcomm_service_name == server_service_name:
        raise InstallError("RFCOMM and server services must use different names")

    rfcomm_service = {
        "kind": "rfcomm",
        "name": rfcomm_service_name,
        "path": _service_path(rfcomm_service_name),
        "content": render_rfcomm_service(config),
    }
    server_service = {
        "kind": "server",
        "name": server_service_name,
        "path": _service_path(server_service_name),
        "content": render_server_service(config, context),
    }
    sudoers_rule = {
        "kind": "sudoers",
        "name": SUDOERS_FILE,
        "path": _sudoers_path(),
        "temp_path": _sudoers_temp_path(),
        "content": render_rfcomm_sudoers(context.server_user, rfcomm_service_name),
    }
    services = [rfcomm_service, server_service]
    required_group = _serial_group()
    frontend_index = context.project_root / "web" / "dist" / "index.html"
    frontend_built = frontend_index.is_file()
    warnings = []
    if not frontend_built:
        warnings.append(
            f"Frontend build not found at {frontend_index}; run `cd web && npm run build`"
        )
    commands = _install_commands(services, sudoers_rule)

    return {
        "services": services,
        "sudoers": sudoers_rule,
        "required_group": required_group,
        "commands": commands,
        "warnings": warnings,
        "project_root": str(context.project_root),
        "config_path": str(context.config_path) if context.config_path else None,
        "server": {
            "host": context.server_host,
            "port": context.server_port,
            "service": context.server_service,
            "user": context.server_user,
        },
        "frontend_built": frontend_built,
        "frontend_index": str(frontend_index),
        # Legacy keys kept for older dry-run consumers while the UI migrates.
        "service_name": rfcomm_service["name"],
        "service_path": rfcomm_service["path"],
        "service_content": rfcomm_service["content"],
    }


def render_rfcomm_service(config):
    device = config["device"]
    port = device["port"]
    name = device["name"]
    mac = device["mac"]
    channel = device["channel"]

    return "\n".join(
        [
            "[Unit]",
            f"Description=Bind RFCOMM for {name} printer",
            "After=bluetooth.target",
            "Wants=bluetooth.target",
            "",
            "[Service]",
            "Type=oneshot",
            f"ExecStartPre=-/usr/bin/rfcomm release {port}",
            f"ExecStart=/usr/bin/rfcomm bind {port} {mac} {channel}",
            f"ExecStop=/usr/bin/rfcomm release {port}",
            "RemainAfterExit=yes",
            "Restart=on-failure",
            "",
            "[Install]",
            "WantedBy=multi-user.target",
            "",
        ]
    )


def render_rfcomm_sudoers(user, service_name):
    return "\n".join(
        [
            "# Generated by KotPrinter install.",
            "# Allows the runtime user to recover only the configured RFCOMM bind.",
            f"{user} ALL=(root) NOPASSWD: {SYSTEMCTL_BIN} restart {service_name}",
            "",
        ]
    )


def render_server_service(config, context):
    rfcomm_service = config["device"]["rfcommService"]
    project_root = str(context.project_root)
    frontend_index = str(context.project_root / "web" / "dist" / "index.html")
    exec_start = [
        PYTHON_BIN,
        "-m",
        "kotprinter.server",
        "--host",
        context.server_host,
        "--port",
        str(context.server_port),
        "--project-root",
        project_root,
        "--server-service",
        context.server_service,
    ]
    if context.config_path is not None:
        exec_start.extend(["--config", str(context.config_path)])

    return "\n".join(
        [
            "[Unit]",
            "Description=KotPrinter web UI and API",
            "After=network.target bluetooth.target",
            f"Wants={rfcomm_service}",
            "",
            "[Service]",
            "Type=simple",
            f"User={context.server_user}",
            f"WorkingDirectory={_unit_arg(project_root)}",
            "Environment=PYTHONUNBUFFERED=1",
            f"ExecStartPre={TEST_BIN} -f {_unit_arg(frontend_index)}",
            f"ExecStart={_unit_command(exec_start)}",
            "Restart=on-failure",
            "RestartSec=3",
            "",
            "[Install]",
            "WantedBy=multi-user.target",
            "",
        ]
    )


def print_install_plan(plan):
    print("KotPrinter install dry run")
    print()
    for warning in plan["warnings"]:
        print(f"[w] {warning}")
    if plan["warnings"]:
        print()

    print("Planned system changes:")
    for service in plan["services"]:
        print(f"- Write systemd unit: {service['path']}")
    sudoers = plan["sudoers"]
    print(f"- Write sudoers rule: {sudoers['path']}")
    print("- Run systemd daemon reload")
    for service in plan["services"]:
        print(f"- Enable and restart: {service['name']}")
    print("- Verify current user's serial group membership")
    print()
    print("Commands that would be run:")
    for service in plan["services"]:
        print(f"sudo -n tee {service['path']} >/dev/null <<'EOF'")
        print(service["content"], end="")
        print("EOF")
        print(f"sudo -n chmod 0644 {service['path']}")
    print(f"sudo -n tee {sudoers['temp_path']} >/dev/null <<'EOF'")
    print(sudoers["content"], end="")
    print("EOF")
    print(f"sudo -n chmod 0440 {sudoers['temp_path']}")
    print(f"sudo -n {VISUDO_BIN} -cf {sudoers['temp_path']}")
    print(f"sudo -n mv {sudoers['temp_path']} {sudoers['path']}")
    print("sudo -n systemctl daemon-reload")
    for service in plan["services"]:
        print(f"sudo -n systemctl enable {service['name']}")
        print(f"sudo -n systemctl restart {service['name']}")

    group = plan["required_group"]
    if group and not _current_user_in_group(group):
        print(f"  # recommended after install: sudo usermod -aG {group} \"$USER\"")


def apply_install_plan(plan):
    if not plan.get("frontend_built", True):
        raise InstallError(
            "Frontend build is missing. Run `cd web && npm run build` before install."
        )

    print("Installing KotPrinter systemd units")
    print()
    for service in plan["services"]:
        _install_service_file(service["content"], service["path"])
        print(f"[i] Wrote {service['path']}")

    sudoers = plan["sudoers"]
    _install_sudoers_file(sudoers["content"], sudoers["temp_path"], sudoers["path"])
    print(f"[i] Wrote {sudoers['path']}")

    _run_sudo(["systemctl", "daemon-reload"])
    print("[i] Ran systemctl daemon-reload")

    for service in plan["services"]:
        _run_sudo(["systemctl", "enable", service["name"]])
        _run_sudo(["systemctl", "restart", service["name"]])
        print(f"[i] Enabled and restarted {service['name']}")

    _print_group_result(plan["required_group"])


def _install_service_file(service_content, service_path):
    _run_sudo(["tee", service_path], input_text=service_content)
    _run_sudo(["chmod", "0644", service_path])


def _install_sudoers_file(sudoers_content, temp_path, final_path):
    try:
        _run_sudo(["tee", temp_path], input_text=sudoers_content)
        _run_sudo(["chmod", "0440", temp_path])
        _run_sudo([VISUDO_BIN, "-cf", temp_path])
        _run_sudo(["mv", temp_path, final_path])
    except InstallError:
        try:
            _run_sudo(["rm", "-f", temp_path])
        except InstallError:
            pass
        raise


def _run_sudo(args, input_text=None):
    command = ["sudo", "-n"] + args
    try:
        result = subprocess.run(
            command,
            check=False,
            input=input_text,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
        )
    except FileNotFoundError as e:
        raise InstallError("sudo is required for install but was not found") from e

    if result.returncode != 0:
        details = (result.stderr or result.stdout or "unknown error").strip()
        shell_command = " ".join(command)
        raise InstallError(f"`{shell_command}` failed: {details}")


def _install_commands(services, sudoers_rule):
    commands = []
    for service in services:
        commands.extend(
            [
                f"sudo -n tee {service['path']} >/dev/null",
                f"sudo -n chmod 0644 {service['path']}",
            ]
        )
    commands.extend(
        [
            f"sudo -n tee {sudoers_rule['temp_path']} >/dev/null",
            f"sudo -n chmod 0440 {sudoers_rule['temp_path']}",
            f"sudo -n {VISUDO_BIN} -cf {sudoers_rule['temp_path']}",
            f"sudo -n mv {sudoers_rule['temp_path']} {sudoers_rule['path']}",
        ]
    )
    commands.append("sudo -n systemctl daemon-reload")
    for service in services:
        commands.append(f"sudo -n systemctl enable {service['name']}")
        commands.append(f"sudo -n systemctl restart {service['name']}")
    return commands


def _service_path(service_name):
    return os.path.join(SYSTEMD_DIR, service_name)


def _sudoers_path():
    return os.path.join(SUDOERS_DIR, SUDOERS_FILE)


def _sudoers_temp_path():
    return os.path.join(SUDOERS_DIR, f".{SUDOERS_FILE}.tmp")


def _validate_project_root(project_root):
    required = ["print.py", "kotprinter", "web"]
    missing = [name for name in required if not (project_root / name).exists()]
    if missing:
        missing_text = ", ".join(missing)
        raise InstallError(
            f"{project_root} does not look like a KotPrinter project root; "
            f"missing: {missing_text}"
        )


def _require_systemd_service_name(value, label):
    if not isinstance(value, str) or not value.strip():
        raise InstallError(f"{label} must be a non-empty systemd service name")
    if "/" in value or value in {".", ".."}:
        raise InstallError(f"{label} must not contain path separators")
    if not value.endswith(".service"):
        raise InstallError(f"{label} must end with .service")
    if any(char.isspace() for char in value):
        raise InstallError(f"{label} must not contain whitespace")
    if not re.fullmatch(r"[A-Za-z0-9_.@-]+\.service", value):
        raise InstallError(
            f"{label} may contain only letters, numbers, dots, underscores, "
            "hyphens, and @"
        )


def _validate_server_host(value):
    if not isinstance(value, str) or not value.strip():
        raise InstallError("server host must be a non-empty string")
    if any(char.isspace() for char in value):
        raise InstallError("server host must not contain whitespace")


def _validate_server_port(value):
    if isinstance(value, bool) or not isinstance(value, int):
        raise InstallError("server port must be an integer")
    if value < 1 or value > 65535:
        raise InstallError("server port must be between 1 and 65535")


def _validate_server_user(value):
    if not isinstance(value, str) or not value.strip():
        raise InstallError("server user must be a non-empty string")
    if any(char.isspace() for char in value):
        raise InstallError("server user must not contain whitespace")
    if not re.fullmatch(r"[A-Za-z_][A-Za-z0-9_.-]*", value):
        raise InstallError("server user must be a sudoers-safe local username")


def _unit_command(args):
    return " ".join(_unit_arg(arg) for arg in args)


def _unit_arg(value):
    text = os.fspath(value)
    if not text:
        return '""'
    if any(char.isspace() or char in {'"', "\\"} for char in text):
        return '"' + text.replace("\\", "\\\\").replace('"', '\\"') + '"'
    return text


def _print_group_result(group):
    if not group:
        print("[w] Could not determine the serial device group.")
        print('    Check `groups "$USER"` before printing without sudo.')
        return

    user = getpass.getuser()
    if _current_user_in_group(group):
        print(f"[i] User {user} is in {group}.")
        return

    print(f"[w] User {user} is not in {group}.")
    print(f"    Run: sudo usermod -aG {group} \"$USER\"")
    print("    Then log out and back in before printing as this user.")


def _serial_group():
    try:
        grp.getgrnam("dialout")
        return "dialout"
    except KeyError:
        return None


def _current_user_in_group(group_name):
    user = getpass.getuser()
    try:
        group = grp.getgrnam(group_name)
    except KeyError:
        return False

    return group.gr_gid in set(os.getgroups()) or user in group.gr_mem
