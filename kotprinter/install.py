import getpass
import grp
import os
import subprocess


SYSTEMD_DIR = "/etc/systemd/system"


class InstallError(Exception):
    pass


def run_install(config, dry_run=False):
    plan = build_install_plan(config)
    if dry_run:
        print_install_plan(plan)
        return 0

    apply_install_plan(plan)
    return 0


def build_install_plan(config):
    service_name = config["device"]["rfcommService"]
    service_path = os.path.join(SYSTEMD_DIR, service_name)
    service_content = render_rfcomm_service(config)
    required_group = _serial_group()

    return {
        "service_name": service_name,
        "service_path": service_path,
        "service_content": service_content,
        "required_group": required_group,
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


def print_install_plan(plan):
    print("KotPrinter install dry run")
    print()
    print("Planned system changes:")
    print(f"- Write systemd unit: {plan['service_path']}")
    print("- Run systemd daemon reload")
    print(f"- Enable and start: {plan['service_name']}")
    print("- Verify current user's serial group membership")
    print()
    print("Commands that would be run:")
    print(f"sudo -n tee {plan['service_path']} >/dev/null <<'EOF'")
    print(plan["service_content"], end="")
    print("EOF")
    print(f"sudo -n chmod 0644 {plan['service_path']}")
    print("sudo -n systemctl daemon-reload")
    print(f"sudo -n systemctl enable --now {plan['service_name']}")

    group = plan["required_group"]
    if group and not _current_user_in_group(group):
        print(f"  # recommended after install: sudo usermod -aG {group} \"$USER\"")


def apply_install_plan(plan):
    print("Installing KotPrinter RFCOMM systemd unit")
    print()
    _install_service_file(plan["service_content"], plan["service_path"])
    print(f"[i] Wrote {plan['service_path']}")

    _run_sudo(["systemctl", "daemon-reload"])
    print("[i] Ran systemctl daemon-reload")

    _run_sudo(["systemctl", "enable", "--now", plan["service_name"]])
    print(f"[i] Enabled and started {plan['service_name']}")

    _print_group_result(plan["required_group"])


def _install_service_file(service_content, service_path):
    _run_sudo(["tee", service_path], input_text=service_content)
    _run_sudo(["chmod", "0644", service_path])


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
