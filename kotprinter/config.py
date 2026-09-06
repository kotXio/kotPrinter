import copy
import json
import os
import re
from dataclasses import dataclass
from typing import List, Optional
from uuid import uuid4


DEFAULT_CONFIG_NAME = "kotprinter.json"
SCHEMA_VERSION = 1

DEFAULT_CONFIG = {
    "schemaVersion": SCHEMA_VERSION,
    "device": {
        "name": "YHK-D0D0",
        "mac": "D6:85:FD:2C:D0:D0",
        "channel": 2,
        "port": "/dev/rfcomm0",
        "baudrate": 115200,
        "rfcommService": "rfcomm-printer.service",
    },
    "printer": {
        "width": 384,
        "feed": 5,
        "repeat": 1,
    },
    "text": {
        "font": "/usr/share/fonts/truetype/dejavu/DejaVuSansMono.ttf",
        "fontSize": 20,
        "padY": 6,
        "align": "left",
        "lineSpacing": 0.5,
        "density": "normal",
    },
    "image": {
        "method": "fs",
        "brightness": 1.0,
        "contrast": 1.0,
        "gamma": 1.0,
        "rotate": 0,
        "fit": "width",
        "height": None,
        "cropAlign": "center",
        "invert": False,
        "threshold": None,
    },
    "history": {
        "enabled": True,
        "retentionDays": 30,
        "cleanupOnStart": True,
    },
}


class ConfigError(Exception):
    pass


@dataclass(frozen=True)
class LoadedConfig:
    data: dict
    path: Optional[str]
    warnings: List[str]


@dataclass(frozen=True)
class ConfigIssue:
    field: str
    message: str

    def as_dict(self):
        return {
            "field": self.field,
            "message": self.message,
        }


@dataclass(frozen=True)
class ConfigValidationResult:
    ok: bool
    data: Optional[dict]
    warnings: List[str]
    errors: List[ConfigIssue]

    def as_dict(self):
        return {
            "ok": self.ok,
            "data": self.data,
            "warnings": list(self.warnings),
            "errors": [error.as_dict() for error in self.errors],
        }


def get_default_config():
    return copy.deepcopy(DEFAULT_CONFIG)


def get_project_config_path(project_root):
    """Return the explicit project-local config path for future server mode."""
    if project_root is None:
        raise ConfigError("Project root cannot be empty")

    root = os.fspath(project_root)
    if root == "":
        raise ConfigError("Project root cannot be empty")

    return os.path.join(os.path.abspath(root), DEFAULT_CONFIG_NAME)


def load_config(path=None):
    config = get_default_config()
    warnings = []
    explicit_path = path is not None
    selected_path = path if explicit_path else DEFAULT_CONFIG_NAME

    if selected_path == "":
        raise ConfigError("Config path cannot be empty")

    if os.path.exists(selected_path):
        raw_config = _read_json_config(selected_path)
        if not isinstance(raw_config, dict):
            raise ConfigError(f"{selected_path}: top-level JSON value must be an object")
        _merge_config(config, raw_config, warnings)
        loaded_path = selected_path
    elif explicit_path:
        raise ConfigError(f"Config file not found: {selected_path}")
    else:
        loaded_path = None

    _validate_config(config)
    return LoadedConfig(config, loaded_path, warnings)


def validate_config_data(raw_config, base_config=None):
    """Validate a proposed config update without writing it to disk."""
    warnings = []
    config = (
        copy.deepcopy(base_config)
        if base_config is not None
        else get_default_config()
    )

    if not isinstance(raw_config, dict):
        return ConfigValidationResult(
            ok=False,
            data=None,
            warnings=warnings,
            errors=[
                ConfigIssue(
                    field="<root>",
                    message="top-level JSON value must be an object",
                )
            ],
        )

    try:
        _merge_config(config, raw_config, warnings)
        _validate_config(config)
    except ConfigError as e:
        return ConfigValidationResult(
            ok=False,
            data=None,
            warnings=warnings,
            errors=[_config_issue_from_error(e)],
        )

    return ConfigValidationResult(
        ok=True,
        data=config,
        warnings=warnings,
        errors=[],
    )


def write_config_atomic(path, raw_config, base_config=None):
    """Validate and save config through a same-directory temp file replace."""
    selected_path = _require_config_path(path)
    validation = validate_config_data(raw_config, base_config=base_config)
    if not validation.ok:
        raise ConfigError(_format_validation_errors(validation.errors))

    _write_json_config_atomic(selected_path, validation.data)
    return LoadedConfig(validation.data, selected_path, validation.warnings)


def _read_json_config(path):
    try:
        with open(path, "r", encoding="utf-8") as config_file:
            return json.load(config_file)
    except json.JSONDecodeError as e:
        raise ConfigError(f"{path}: invalid JSON at line {e.lineno}, column {e.colno}") from e
    except OSError as e:
        raise ConfigError(f"Cannot read config file {path}: {e}") from e


def _write_json_config_atomic(path, config):
    final_path = os.path.abspath(path)
    directory = os.path.dirname(final_path)
    if not os.path.isdir(directory):
        raise ConfigError(f"Config directory not found: {directory}")

    basename = os.path.basename(final_path)
    tmp_path = os.path.join(
        directory,
        f".{basename}.tmp-{os.getpid()}-{uuid4().hex}",
    )

    try:
        with open(tmp_path, "w", encoding="utf-8") as config_file:
            json.dump(config, config_file, indent=2)
            config_file.write("\n")
            config_file.flush()
            os.fsync(config_file.fileno())
        os.replace(tmp_path, final_path)
    except OSError as e:
        try:
            if os.path.exists(tmp_path):
                os.unlink(tmp_path)
        except OSError:
            pass
        raise ConfigError(f"Cannot write config file {path}: {e}") from e


def _merge_config(base, override, warnings, prefix=""):
    for key, value in override.items():
        path = f"{prefix}.{key}" if prefix else key
        if key not in base:
            warnings.append(f"Unknown config key ignored: {path}")
            continue

        if isinstance(base[key], dict):
            if not isinstance(value, dict):
                raise ConfigError(f"{path} must be an object")
            _merge_config(base[key], value, warnings, path)
        else:
            base[key] = value


def _validate_config(config):
    _require_int(config, "schemaVersion", minimum=1)
    if config["schemaVersion"] != SCHEMA_VERSION:
        raise ConfigError(
            f"Unsupported schemaVersion {config['schemaVersion']}; expected {SCHEMA_VERSION}"
        )

    device = config["device"]
    _require_non_empty_string(device, "device.name")
    _require_single_line_string(device, "device.name")
    _require_mac(device, "device.mac")
    _require_int(device, "device.channel", minimum=1)
    _require_non_empty_string(device, "device.port")
    _require_absolute_path(device, "device.port")
    _require_int(device, "device.baudrate", minimum=1)
    _require_non_empty_string(device, "device.rfcommService")
    _require_systemd_service_name(device, "device.rfcommService")

    printer = config["printer"]
    _require_int(printer, "printer.width", minimum=1)
    if printer["width"] % 8 != 0:
        raise ConfigError("printer.width must be divisible by 8")
    _require_int(printer, "printer.feed", minimum=0)
    _require_int(printer, "printer.repeat", minimum=1)

    text = config["text"]
    _require_non_empty_string(text, "text.font")
    _require_int(text, "text.fontSize", minimum=1)
    _require_int(text, "text.padY", minimum=0)
    _require_choice(text, "text.align", {"left", "center", "right"})
    _require_number(text, "text.lineSpacing", minimum=0)
    _require_choice(text, "text.density", {"light", "normal", "dark"})

    image = config["image"]
    _require_choice(image, "image.method", {"fs", "ordered", "th"})
    _require_number(image, "image.brightness", minimum=0, exclusive=True)
    _require_number(image, "image.contrast", minimum=0, exclusive=True)
    _require_number(image, "image.gamma", minimum=0, exclusive=True)
    _require_choice(image, "image.rotate", {0, 90, 180, 270})
    _require_choice(
        image,
        "image.fit",
        {"width", "contain", "cover", "stretch", "none", "autofit"},
    )
    _require_optional_int(image, "image.height", minimum=1)
    _require_choice(image, "image.cropAlign", {"top", "center", "bottom"})
    _require_bool(image, "image.invert")
    _require_optional_int(image, "image.threshold", minimum=0, maximum=255)

    history = config["history"]
    _require_bool(history, "history.enabled")
    _require_optional_int(history, "history.retentionDays", minimum=0)
    _require_bool(history, "history.cleanupOnStart")


def _require_int(section, dotted_key, minimum=None):
    key = dotted_key.rsplit(".", 1)[-1]
    value = section[key]
    if isinstance(value, bool) or not isinstance(value, int):
        raise ConfigError(f"{dotted_key} must be an integer")
    if minimum is not None and value < minimum:
        raise ConfigError(f"{dotted_key} must be {minimum} or greater")


def _require_optional_int(section, dotted_key, minimum=None, maximum=None):
    key = dotted_key.rsplit(".", 1)[-1]
    value = section[key]
    if value is None:
        return
    if isinstance(value, bool) or not isinstance(value, int):
        raise ConfigError(f"{dotted_key} must be an integer or null")
    if minimum is not None and value < minimum:
        raise ConfigError(f"{dotted_key} must be {minimum} or greater")
    if maximum is not None and value > maximum:
        raise ConfigError(f"{dotted_key} must be {maximum} or less")


def _require_bool(section, dotted_key):
    key = dotted_key.rsplit(".", 1)[-1]
    value = section[key]
    if not isinstance(value, bool):
        raise ConfigError(f"{dotted_key} must be true or false")


def _require_number(section, dotted_key, minimum=None, exclusive=False):
    key = dotted_key.rsplit(".", 1)[-1]
    value = section[key]
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise ConfigError(f"{dotted_key} must be a number")
    if minimum is None:
        return
    if exclusive and value <= minimum:
        raise ConfigError(f"{dotted_key} must be greater than {minimum}")
    if not exclusive and value < minimum:
        raise ConfigError(f"{dotted_key} must be {minimum} or greater")


def _require_non_empty_string(section, dotted_key):
    key = dotted_key.rsplit(".", 1)[-1]
    value = section[key]
    if not isinstance(value, str) or not value.strip():
        raise ConfigError(f"{dotted_key} must be a non-empty string")


def _require_single_line_string(section, dotted_key):
    key = dotted_key.rsplit(".", 1)[-1]
    value = section[key]
    if any(char in value for char in "\r\n"):
        raise ConfigError(f"{dotted_key} must be a single-line string")


def _require_absolute_path(section, dotted_key):
    key = dotted_key.rsplit(".", 1)[-1]
    value = section[key]
    if not isinstance(value, str) or not value.startswith("/"):
        raise ConfigError(f"{dotted_key} must be an absolute path")
    if any(char.isspace() for char in value):
        raise ConfigError(f"{dotted_key} must not contain whitespace")


def _require_systemd_service_name(section, dotted_key):
    key = dotted_key.rsplit(".", 1)[-1]
    value = section[key]
    if not isinstance(value, str):
        raise ConfigError(f"{dotted_key} must be a systemd service name")
    if "/" in value or value in {".", ".."}:
        raise ConfigError(f"{dotted_key} must not contain path separators")
    if not value.endswith(".service"):
        raise ConfigError(f"{dotted_key} must end with .service")
    if any(char.isspace() for char in value):
        raise ConfigError(f"{dotted_key} must not contain whitespace")
    if not re.fullmatch(r"[A-Za-z0-9_.@-]+\.service", value):
        raise ConfigError(
            f"{dotted_key} may contain only letters, numbers, dots, underscores, "
            "hyphens, and @"
        )


def _require_choice(section, dotted_key, choices):
    key = dotted_key.rsplit(".", 1)[-1]
    value = section[key]
    if value not in choices:
        choices_text = ", ".join(str(choice) for choice in sorted(choices))
        raise ConfigError(f"{dotted_key} must be one of: {choices_text}")


def _require_mac(section, dotted_key):
    key = dotted_key.rsplit(".", 1)[-1]
    value = section[key]
    if not isinstance(value, str) or not re.fullmatch(
        r"[0-9a-f]{2}(:[0-9a-f]{2}){5}", value, flags=re.I
    ):
        raise ConfigError(f"{dotted_key} must be a Bluetooth MAC address")


def _require_config_path(path):
    if path is None:
        raise ConfigError("Config path is required")

    selected_path = os.fspath(path)
    if selected_path == "":
        raise ConfigError("Config path cannot be empty")

    return selected_path


def _config_issue_from_error(error):
    message = str(error)
    return ConfigIssue(
        field=_field_from_error_message(message),
        message=message,
    )


def _field_from_error_message(message):
    if message.startswith("Unsupported schemaVersion"):
        return "schemaVersion"

    token = message.split(" ", 1)[0].rstrip(":")
    if re.fullmatch(r"[A-Za-z][A-Za-z0-9]*(\.[A-Za-z][A-Za-z0-9]*)*", token):
        return token

    return "<root>"


def _format_validation_errors(errors):
    if not errors:
        return "Invalid config"
    if len(errors) == 1:
        return errors[0].message
    return "Invalid config: " + "; ".join(error.message for error in errors)
