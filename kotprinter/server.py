from __future__ import annotations

import argparse
import json
import mimetypes
import os
import tempfile
import threading
from dataclasses import asdict, dataclass
from email import policy
from email.parser import BytesParser
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Any, Dict, Optional
from urllib.parse import parse_qs, unquote, urlparse

from . import __version__
from .checks import check_exit_code, run_checks
from .config import (
    ConfigError,
    DEFAULT_CONFIG,
    get_default_config,
    get_project_config_path,
    load_config,
    validate_config_data,
    write_config_atomic,
)
from .core import (
    DeviceSettings,
    ImageJob,
    ImageSettings,
    PrinterSettings,
    RenderSettings,
    RuntimeSettings,
    TextJob,
    TextSettings,
    resolve_runtime_settings,
)
from .install import (
    DEFAULT_SERVER_HOST,
    DEFAULT_SERVER_PORT,
    DEFAULT_SERVER_SERVICE,
    InstallError,
    build_install_plan,
    resolve_install_context,
)
from .job_store import (
    STATUS_CANCELED,
    STATUS_DONE,
    STATUS_FAILED,
    STATUS_PRINTING,
    STATUS_QUEUED,
    JobNotFoundError,
    JobStore,
    JobStoreError,
)
from .print_queue import (
    ACTIVE_QUEUE_STATUSES,
    QUEUE_STATUS_PRINTING,
    PrintQueue,
    PrintQueueError,
    QueueEntry,
)
from .render import RenderError, load_image, render_image_job, render_text_job
from .transport import (
    TransportError,
    TransportWriteError,
    close_serial,
    feed_paper,
    get_printer_info,
    initialize_printer,
    is_rfcomm_bound,
    open_printer,
    print_raster_image,
)


DEFAULT_HOST = "127.0.0.1"
DEFAULT_PORT = 8000
MAX_BODY_BYTES = 25 * 1024 * 1024
FRONTEND_DIST_RELATIVE_PATH = Path("web") / "dist"
FRONTEND_INDEX_FILE = "index.html"

WAKE_RETRIES = 3
WAKE_RETRY_DELAY = 1.0

RASTER_BAND_HEIGHT = 64
RASTER_BAND_PAUSE = 0.12
RASTER_CHUNK_SIZE = 128
RASTER_CHUNK_PAUSE = 0.03
RASTER_JOB_PAUSE = 0.4


@dataclass(frozen=True)
class LoadedServerConfig:
    data: Dict[str, Any]
    loaded_path: Optional[str]
    warnings: list[str]
    exists: bool


@dataclass(frozen=True)
class UploadedFile:
    field_name: str
    filename: str
    content_type: str
    data: bytes


class ApiError(Exception):
    def __init__(
        self,
        status: int,
        code: str,
        message: str,
        *,
        field: Optional[str] = None,
        details: Optional[Any] = None,
    ):
        super().__init__(message)
        self.status = status
        self.code = code
        self.message = message
        self.field = field
        self.details = details

    def as_dict(self) -> Dict[str, Any]:
        error = {
            "code": self.code,
            "message": self.message,
        }
        if self.field is not None:
            error["field"] = self.field
        if self.details is not None:
            error["details"] = self.details
        return error


class KotPrinterServer:
    def __init__(
        self,
        *,
        project_root: str | Path,
        config_path: Optional[str | Path] = None,
        data_root: Optional[str | Path] = None,
        static_root: Optional[str | Path] = None,
        server_host: str = DEFAULT_SERVER_HOST,
        server_port: int = DEFAULT_SERVER_PORT,
        server_service: str = DEFAULT_SERVER_SERVICE,
    ):
        self.project_root = Path(project_root).resolve()
        self.config_path = (
            Path(config_path).resolve()
            if config_path is not None
            else Path(get_project_config_path(self.project_root))
        )
        self.data_root = (
            Path(data_root).resolve()
            if data_root is not None
            else self.project_root / "data"
        )
        self.static_root = (
            Path(static_root).resolve()
            if static_root is not None
            else self.project_root / FRONTEND_DIST_RELATIVE_PATH
        )
        self.server_host = server_host
        self.server_port = server_port
        self.server_service = server_service
        self.job_store = JobStore(self.data_root)
        self.transport_lock = threading.Lock()
        self.print_queue = PrintQueue(self._run_queued_print)
        self.startup_cleanup = self._cleanup_history_on_start()

    def load_config(self) -> LoadedServerConfig:
        if not self.config_path.exists():
            return LoadedServerConfig(
                data=get_default_config(),
                loaded_path=None,
                warnings=[],
                exists=False,
            )

        try:
            loaded = load_config(str(self.config_path))
        except ConfigError as e:
            raise ApiError(500, "config_error", str(e)) from e

        return LoadedServerConfig(
            data=loaded.data,
            loaded_path=loaded.path,
            warnings=loaded.warnings,
            exists=True,
        )

    def active_settings(self) -> RuntimeSettings:
        loaded = self.load_config()
        return resolve_runtime_settings(
            loaded.data,
            default_image_rotate=DEFAULT_CONFIG["image"]["rotate"],
        )

    def health(self) -> Dict[str, Any]:
        return {
            "ok": True,
            "service": "kotprinter",
            "version": __version__,
        }

    def version(self) -> Dict[str, Any]:
        return {
            "ok": True,
            "name": "kotPrinter",
            "version": __version__,
        }

    def settings_response(self) -> Dict[str, Any]:
        loaded = self.load_config()
        return {
            "ok": True,
            "settings": loaded.data,
            "configPath": str(self.config_path),
            "loadedPath": loaded.loaded_path,
            "configExists": loaded.exists,
            "warnings": loaded.warnings,
        }

    def validate_settings(self, payload: Any) -> Dict[str, Any]:
        loaded = self.load_config()
        validation = validate_config_data(payload, base_config=loaded.data)
        return validation.as_dict()

    def update_settings(self, payload: Any) -> Dict[str, Any]:
        loaded = self.load_config()
        try:
            saved = write_config_atomic(
                str(self.config_path),
                payload,
                base_config=loaded.data,
            )
        except ConfigError as e:
            validation = validate_config_data(payload, base_config=loaded.data)
            if not validation.ok:
                raise ApiError(
                    422,
                    "invalid_settings",
                    "Settings validation failed",
                    details={
                        "errors": [
                            error.as_dict()
                            for error in validation.errors
                        ],
                    },
                ) from e
            raise ApiError(500, "config_write_failed", str(e)) from e

        return {
            "ok": True,
            "settings": saved.data,
            "configPath": str(self.config_path),
            "loadedPath": saved.path,
            "warnings": saved.warnings,
        }

    def check(self, *, live: bool = False) -> Dict[str, Any]:
        loaded = self.load_config()
        if live:
            with self.transport_lock:
                results = run_checks(
                    loaded.data,
                    config_path=loaded.loaded_path,
                    config_warnings=loaded.warnings,
                    live=True,
                    project_root=self.project_root,
                    server_port=self.server_port,
                    server_service=self.server_service,
                )
        else:
            results = run_checks(
                loaded.data,
                config_path=loaded.loaded_path,
                config_warnings=loaded.warnings,
                live=False,
                project_root=self.project_root,
                server_port=self.server_port,
                server_service=self.server_service,
            )

        return {
            "ok": check_exit_code(results) == 0,
            "results": [result.as_dict() for result in results],
        }

    def printer_status(self) -> Dict[str, Any]:
        loaded = self.load_config()
        settings = resolve_runtime_settings(
            loaded.data,
            default_image_rotate=DEFAULT_CONFIG["image"]["rotate"],
        )
        rfcomm_bound = is_rfcomm_bound(settings)
        jobs = self.job_store.list_jobs(limit=1)
        last_job = jobs[-1] if jobs else None
        return {
            "ok": True,
            "configured": loaded.exists,
            "configPath": str(self.config_path),
            "rfcommBound": rfcomm_bound,
            "connectionState": "idle" if rfcomm_bound else "rfcomm-missing",
            "lastJob": last_job,
            "lastKnownBatteryPercent": None,
            "queue": self.print_queue.snapshot(),
            "note": "Idle closed Bluetooth connection is normal for this printer",
        }

    def queue_status(self) -> Dict[str, Any]:
        return {
            "ok": True,
            "queue": self.print_queue.snapshot(),
        }

    def printer_info(self) -> Dict[str, Any]:
        settings = self.active_settings()
        with self.transport_lock:
            opened = open_printer(
                settings,
                retries=WAKE_RETRIES,
                quiet=True,
                wake_retry_delay=WAKE_RETRY_DELAY,
            )
            try:
                info = get_printer_info(opened.serial, settings)
            finally:
                close_serial(opened.serial)

        return {
            "ok": True,
            "printer": {
                "voltageMv": info.voltage_mv,
                "dpi": info.dpi,
                "batteryPercent": info.battery_percent,
                "serialNumber": info.serial_number,
            },
            "settings": asdict(settings),
        }

    def install_dry_run(self) -> Dict[str, Any]:
        loaded = self.load_config()
        default_config_path = Path(get_project_config_path(self.project_root)).resolve()
        config_path = None if self.config_path == default_config_path else self.config_path
        try:
            context = resolve_install_context(
                project_root=self.project_root,
                config_path=config_path,
                server_host=self.server_host,
                server_port=self.server_port,
                server_service=self.server_service,
            )
            plan = build_install_plan(loaded.data, context=context)
        except InstallError as e:
            raise ApiError(500, "install_plan_failed", str(e)) from e

        return {
            "ok": True,
            "dryRun": True,
            "plan": {
                "services": plan["services"],
                "requiredGroup": plan["required_group"],
                "commands": plan["commands"],
                "warnings": plan["warnings"],
                "projectRoot": plan["project_root"],
                "configPath": plan["config_path"],
                "server": plan["server"],
                "frontendBuilt": plan["frontend_built"],
                "frontendIndex": plan["frontend_index"],
                "serviceName": plan["service_name"],
                "servicePath": plan["service_path"],
                "serviceContent": plan["service_content"],
            },
        }

    def create_text_job(self, payload: Any) -> Dict[str, Any]:
        payload = _require_object_payload(payload)
        text = payload.get("text")
        if not isinstance(text, str):
            raise ApiError(
                400,
                "invalid_request",
                "`text` must be a string",
                field="text",
            )

        settings = self._job_settings("text", payload)
        job = TextJob(text=text, settings=settings)
        try:
            render_result = (
                render_text_job(job)
                if payload.get("render", True)
                else None
            )
        except RenderError as e:
            raise ApiError(422, "render_failed", str(e)) from e

        stored = self.job_store.create_text_job(job, render_result=render_result)
        return {
            "ok": True,
            "job": self.job_store.get_job(stored.job_id),
        }

    def create_image_job(
        self,
        fields: Dict[str, Any],
        upload: UploadedFile,
    ) -> Dict[str, Any]:
        settings = self._job_settings("img", fields)
        suffix = Path(upload.filename).suffix
        temp_path = None
        try:
            with tempfile.NamedTemporaryFile(delete=False, suffix=suffix) as temp_file:
                temp_file.write(upload.data)
                temp_path = temp_file.name

            job = ImageJob(path=temp_path, settings=settings)
            render_result = (
                render_image_job(job)
                if fields.get("render", True)
                else None
            )
            stored = self.job_store.create_image_job(job, render_result=render_result)
            self.job_store.update_job(
                stored.job_id,
                metadata={
                    "upload": {
                        "filename": upload.filename,
                        "contentType": upload.content_type,
                    },
                },
            )
            return {
                "ok": True,
                "job": self.job_store.get_job(stored.job_id),
            }
        except RenderError as e:
            raise ApiError(422, "render_failed", str(e)) from e
        except JobStoreError as e:
            raise ApiError(500, "job_store_error", str(e)) from e
        finally:
            if temp_path is not None:
                try:
                    os.unlink(temp_path)
                except OSError:
                    pass

    def list_jobs(self, *, limit: Optional[int] = None) -> Dict[str, Any]:
        return {
            "ok": True,
            "jobs": self.job_store.list_jobs(limit=limit),
            "queue": self.print_queue.snapshot(),
        }

    def history(self, *, limit: Optional[int] = None) -> Dict[str, Any]:
        loaded = self.load_config()
        history_config = loaded.data["history"]
        return {
            "ok": True,
            "history": self.job_store.list_jobs(limit=limit),
            "settings": history_config,
            "queue": self.print_queue.snapshot(),
            "startupCleanup": self.startup_cleanup,
        }

    def cleanup_history(self, payload: Any) -> Dict[str, Any]:
        payload = _require_object_payload(payload)
        loaded = self.load_config()
        history_config = dict(loaded.data["history"])
        if payload:
            history_config.update(_validate_history_cleanup_overrides(payload))

        try:
            result = self.job_store.cleanup_history(
                retention_days=history_config["retentionDays"],
                enabled=history_config["enabled"],
                active_job_ids=self._active_job_ids(),
            )
        except JobStoreError as e:
            raise ApiError(500, "history_cleanup_failed", str(e)) from e

        return {
            "ok": not result["errors"],
            "cleanup": result,
            "settings": history_config,
        }

    def get_job(self, job_id: str) -> Dict[str, Any]:
        try:
            return {
                "ok": True,
                "job": self.job_store.get_job(job_id),
                "queue": _queue_entry_dict(
                    self.print_queue.latest_entry_for_job(job_id)
                ),
            }
        except JobStoreError as e:
            raise ApiError(404, "job_not_found", str(e)) from e

    def get_preview_path(self, job_id: str) -> Path:
        try:
            return self.job_store.get_preview_path(job_id)
        except JobStoreError as e:
            raise ApiError(404, "preview_not_found", str(e)) from e

    def get_source_path(self, job_id: str) -> Path:
        try:
            return self.job_store.get_source_path(job_id)
        except JobStoreError as e:
            raise ApiError(404, "source_not_found", str(e)) from e

    def get_raster_path(self, job_id: str) -> Path:
        try:
            return self.job_store.get_raster_path(job_id)
        except JobStoreError as e:
            raise ApiError(404, "raster_not_found", str(e)) from e

    def delete_job(self, job_id: str) -> Dict[str, Any]:
        try:
            deleted = self.job_store.delete_job(
                job_id,
                active_job_ids=self._active_job_ids(),
            )
        except JobNotFoundError as e:
            raise ApiError(404, "job_not_found", str(e)) from e
        except JobStoreError as e:
            raise ApiError(409, "job_delete_failed", str(e)) from e

        return {
            "ok": True,
            "deleted": deleted,
        }

    def print_job(self, job_id: str, *, reprint: bool = False) -> Dict[str, Any]:
        self._require_printable_job(job_id)
        action = "reprint" if reprint else "print"
        try:
            entry = self.print_queue.enqueue(job_id, action, submit=False)
        except PrintQueueError as e:
            active = self.print_queue.active_entry_for_job(job_id)
            raise ApiError(
                409,
                "job_already_queued",
                str(e),
                details={"queue": _queue_entry_dict(active)},
            ) from e

        try:
            record = self.job_store.update_job(
                job_id,
                status=STATUS_QUEUED,
                metadata={"queue": entry.as_dict()},
            )
        except Exception:
            self.print_queue.discard_unsubmitted(entry)
            raise

        self.print_queue.submit(entry)
        return {
            "ok": True,
            "queued": True,
            "job": record,
            "queue": entry.as_dict(),
        }

    def cancel_job(self, job_id: str) -> Dict[str, Any]:
        try:
            record = self.job_store.get_job(job_id)
        except JobStoreError as e:
            raise ApiError(404, "job_not_found", str(e)) from e

        queue_state, entry = self.print_queue.cancel_job(job_id)
        if queue_state == "canceled" and entry is not None:
            record = self.job_store.update_job(
                job_id,
                status=STATUS_CANCELED,
                errors=[entry.error],
                metadata={"queue": entry.as_dict()},
            )
            return {
                "ok": True,
                "job": record,
                "queue": entry.as_dict(),
            }

        if queue_state == QUEUE_STATUS_PRINTING and entry is not None:
            record = self.job_store.update_job(
                job_id,
                status=STATUS_PRINTING,
                metadata={"cancelRequest": entry.as_dict()},
            )
            return {
                "ok": True,
                "cancelRequested": True,
                "message": "Job is already printing; cancellation is best-effort",
                "job": record,
                "queue": entry.as_dict(),
            }

        if record.get("status") in {STATUS_PRINTING, STATUS_DONE}:
            raise ApiError(
                409,
                "job_not_cancelable",
                f"Job cannot be canceled in status {record.get('status')}",
            )

        error = {
            "code": "job_canceled",
            "message": "Job was canceled before printing",
        }
        record = self.job_store.update_job(
            job_id,
            status=STATUS_CANCELED,
            errors=[error],
        )
        return {
            "ok": True,
            "job": record,
        }

    def _run_queued_print(self, entry: QueueEntry) -> Dict[str, Any]:
        try:
            result_payload = self._execute_print_job(
                entry.job_id,
                reprint=entry.action == "reprint",
                queue_id=entry.queue_id,
            )
        except TransportError as e:
            error = _transport_error_dict(e, queue_id=entry.queue_id)
            self.job_store.update_job(
                entry.job_id,
                status=STATUS_FAILED,
                errors=[error],
                metadata={
                    "printError": error,
                    "queue": _queue_entry_dict(entry, status=STATUS_FAILED),
                },
            )
            raise
        except Exception as e:
            error = {
                "code": e.__class__.__name__,
                "message": str(e),
                "queueId": entry.queue_id,
            }
            self.job_store.update_job(
                entry.job_id,
                status=STATUS_FAILED,
                errors=[error],
                metadata={
                    "printError": error,
                    "queue": _queue_entry_dict(entry, status=STATUS_FAILED),
                },
            )
            raise

        record = self.job_store.update_job(
            entry.job_id,
            status=STATUS_DONE,
            warnings=result_payload["warnings"],
            metadata={
                "printResult": result_payload,
                "queue": _queue_entry_dict(entry, status=STATUS_DONE),
            },
        )
        return {
            "jobId": record["jobId"],
            "status": record["status"],
            "printResult": result_payload,
        }

    def _execute_print_job(
        self,
        job_id: str,
        *,
        reprint: bool,
        queue_id: str,
    ) -> Dict[str, Any]:
        record, raster_path = self._require_printable_job(job_id)
        settings = runtime_settings_from_snapshot(record["settings"])
        try:
            image = load_image(str(raster_path))
        except RenderError as e:
            raise ApiError(500, "raster_load_failed", str(e)) from e

        self.job_store.update_job(
            job_id,
            status=STATUS_PRINTING,
            metadata={"queue": {"queueId": queue_id, "status": STATUS_PRINTING}},
        )

        with self.transport_lock:
            opened = open_printer(
                settings,
                retries=WAKE_RETRIES,
                quiet=False,
                wake_retry_delay=WAKE_RETRY_DELAY,
            )
            try:
                initialize_printer(opened.serial)
                print_result = print_raster_image(
                    opened.serial,
                    image,
                    settings,
                    band_height=RASTER_BAND_HEIGHT,
                    band_pause=RASTER_BAND_PAUSE,
                    chunk_size=RASTER_CHUNK_SIZE,
                    chunk_pause=RASTER_CHUNK_PAUSE,
                    job_pause=RASTER_JOB_PAUSE,
                )
                feed_result = feed_paper(opened.serial, settings)
            finally:
                close_serial(opened.serial)

        return {
            "bytesWritten": print_result.bytes_written + feed_result.bytes_written,
            "rasterBytesWritten": print_result.bytes_written,
            "feedBytesWritten": feed_result.bytes_written,
            "warnings": list(print_result.warnings) + list(feed_result.warnings),
            "metadata": dict(print_result.metadata),
            "reprint": reprint,
            "queueId": queue_id,
        }

    def _require_printable_job(self, job_id: str) -> tuple[Dict[str, Any], Path]:
        try:
            record = self.job_store.get_job(job_id)
        except JobStoreError as e:
            raise ApiError(404, "job_not_found", str(e)) from e

        if record.get("status") == STATUS_CANCELED:
            raise ApiError(409, "job_canceled", f"Job is canceled: {job_id}")

        try:
            raster_path = self.job_store.get_artifact_path(job_id, "raster")
        except JobStoreError as e:
            raise ApiError(409, "job_not_printable", str(e)) from e

        return record, raster_path

    def _active_job_ids(self) -> set[str]:
        return {
            entry["jobId"]
            for entry in self.print_queue.snapshot()["entries"]
            if entry["status"] in ACTIVE_QUEUE_STATUSES
        }

    def _cleanup_history_on_start(self) -> Optional[Dict[str, Any]]:
        try:
            loaded = self.load_config()
            history_config = loaded.data["history"]
            if not history_config["cleanupOnStart"]:
                return None
            return self.job_store.cleanup_history(
                retention_days=history_config["retentionDays"],
                enabled=history_config["enabled"],
                active_job_ids=self._active_job_ids(),
            )
        except Exception as e:
            return {
                "enabled": False,
                "errors": [
                    {
                        "message": str(e),
                    }
                ],
            }

    def _job_settings(self, command: str, payload: Dict[str, Any]) -> RuntimeSettings:
        loaded = self.load_config()
        preset = payload.get("preset")
        overrides = normalize_job_options(command, payload)
        try:
            return resolve_runtime_settings(
                loaded.data,
                command=command,
                preset=preset,
                overrides=overrides,
                default_image_rotate=DEFAULT_CONFIG["image"]["rotate"],
            )
        except ValueError as e:
            raise ApiError(422, "invalid_preset", str(e), field="preset") from e


class KotPrinterHTTPServer(ThreadingHTTPServer):
    daemon_threads = True
    allow_reuse_address = True

    def __init__(self, server_address, handler_class, app: KotPrinterServer):
        super().__init__(server_address, handler_class)
        self.app = app


class KotPrinterRequestHandler(BaseHTTPRequestHandler):
    server_version = "kotprinter-http/0.4"

    def do_OPTIONS(self):
        self.send_response(204)
        self._send_common_headers()
        self.end_headers()

    def do_GET(self):
        self._handle("GET")

    def do_POST(self):
        self._handle("POST")

    def do_PUT(self):
        self._handle("PUT")

    def do_DELETE(self):
        self._handle("DELETE")

    def log_message(self, format, *args):
        return

    @property
    def app(self) -> KotPrinterServer:
        return self.server.app

    def _handle(self, method: str):
        try:
            parsed = urlparse(self.path)
            path = parsed.path.rstrip("/") or "/"
            query = parse_qs(parsed.query)
            response = self._dispatch(method, path, query)
            if response is not None:
                status, payload = response
                self._send_json(status, payload)
        except ApiError as e:
            self._send_json(e.status, {"ok": False, "error": e.as_dict()})
        except TransportError as e:
            self._send_json(503, {"ok": False, "error": {
                "code": "printer_unavailable",
                "message": str(e),
            }})
        except Exception as e:
            self._send_json(500, {"ok": False, "error": {
                "code": "internal_error",
                "message": str(e),
            }})

    def _dispatch(self, method: str, path: str, query: Dict[str, list[str]]):
        if method == "GET" and path == "/api/health":
            return 200, self.app.health()
        if method == "GET" and path == "/api/version":
            return 200, self.app.version()
        if method == "GET" and path == "/api/check":
            return 200, self.app.check(live=False)
        if method == "GET" and path == "/api/check/live":
            return 200, self.app.check(live=True)
        if method == "GET" and path == "/api/printer/status":
            return 200, self.app.printer_status()
        if method == "GET" and path == "/api/queue":
            return 200, self.app.queue_status()
        if method == "GET" and path == "/api/printer/info":
            return 200, self.app.printer_info()
        if method == "GET" and path == "/api/settings":
            return 200, self.app.settings_response()
        if method == "PUT" and path == "/api/settings":
            return 200, self.app.update_settings(self._read_json_body())
        if method == "POST" and path == "/api/settings/validate":
            return 200, self.app.validate_settings(self._read_json_body())
        if method == "POST" and path == "/api/jobs/text":
            return 201, self.app.create_text_job(self._read_json_body())
        if method == "POST" and path == "/api/jobs/image":
            fields, files = self._read_multipart_body()
            upload = (
                files.get("file")
                or files.get("image")
                or next(iter(files.values()), None)
            )
            if upload is None:
                raise ApiError(400, "missing_file", "multipart file field is required")
            return 201, self.app.create_image_job(fields, upload)
        if method == "GET" and path == "/api/jobs":
            return 200, self.app.list_jobs(limit=_query_int(query, "limit"))
        if method == "GET" and path == "/api/history":
            return 200, self.app.history(limit=_query_int(query, "limit"))
        if method == "POST" and path == "/api/history/cleanup":
            return 200, self.app.cleanup_history(self._read_json_body())
        if method == "POST" and path == "/api/system/install/dry-run":
            return 200, self.app.install_dry_run()

        segments = [segment for segment in path.split("/") if segment]
        if len(segments) >= 3 and segments[0] == "api" and segments[1] == "jobs":
            job_id = segments[2]
            if method == "GET" and len(segments) == 3:
                return 200, self.app.get_job(job_id)
            if method == "GET" and len(segments) == 4 and segments[3] == "preview":
                self._send_file(self.app.get_preview_path(job_id), "image/png")
                return None
            if method == "GET" and len(segments) == 4 and segments[3] == "source":
                source_path = self.app.get_source_path(job_id)
                self._send_file(source_path, _content_type_for_path(source_path))
                return None
            if method == "GET" and len(segments) == 4 and segments[3] == "raster":
                self._send_file(self.app.get_raster_path(job_id), "image/png")
                return None
            if method == "POST" and len(segments) == 4 and segments[3] == "print":
                return 202, self.app.print_job(job_id)
            if method == "POST" and len(segments) == 4 and segments[3] == "reprint":
                return 202, self.app.print_job(job_id, reprint=True)
            if method == "POST" and len(segments) == 4 and segments[3] == "cancel":
                return 200, self.app.cancel_job(job_id)
            if method == "DELETE" and len(segments) == 3:
                return 200, self.app.delete_job(job_id)

        if method == "GET" and not _is_api_path(path):
            self._send_frontend_asset(path)
            return None

        raise ApiError(404, "not_found", f"No route for {method} {path}")

    def _read_json_body(self):
        content_type = self.headers.get("Content-Type", "")
        if content_type and "application/json" not in content_type:
            raise ApiError(415, "unsupported_media_type", "Expected application/json")

        body = self._read_body()
        if not body:
            return {}
        try:
            return json.loads(body.decode("utf-8"))
        except json.JSONDecodeError as e:
            raise ApiError(
                400,
                "invalid_json",
                f"Invalid JSON at line {e.lineno}, column {e.colno}",
            ) from e

    def _read_multipart_body(self):
        content_type = self.headers.get("Content-Type", "")
        if "multipart/form-data" not in content_type:
            raise ApiError(
                415,
                "unsupported_media_type",
                "Expected multipart/form-data",
            )

        body = self._read_body()
        headers = (
            f"Content-Type: {content_type}\r\n"
            "MIME-Version: 1.0\r\n\r\n"
        ).encode("utf-8")
        message = BytesParser(policy=policy.default).parsebytes(headers + body)
        if not message.is_multipart():
            raise ApiError(400, "invalid_multipart", "Multipart body is invalid")

        fields: Dict[str, Any] = {}
        files: Dict[str, UploadedFile] = {}
        for part in message.iter_parts():
            if part.get_content_disposition() != "form-data":
                continue

            name = part.get_param("name", header="content-disposition")
            if not name:
                continue

            payload = part.get_payload(decode=True) or b""
            filename = part.get_filename()
            if filename:
                files[name] = UploadedFile(
                    field_name=name,
                    filename=filename,
                    content_type=part.get_content_type(),
                    data=payload,
                )
            else:
                charset = part.get_content_charset() or "utf-8"
                fields[name] = coerce_form_value(payload.decode(charset))

        if isinstance(fields.get("options"), str):
            fields["options"] = _parse_options_json(fields["options"])

        return fields, files

    def _read_body(self) -> bytes:
        try:
            length = int(self.headers.get("Content-Length", "0"))
        except ValueError as e:
            raise ApiError(
                400,
                "invalid_content_length",
                "Invalid Content-Length",
            ) from e

        if length > MAX_BODY_BYTES:
            raise ApiError(413, "payload_too_large", "Request body is too large")
        return self.rfile.read(length)

    def _send_json(self, status: int, payload: Dict[str, Any]):
        body = json.dumps(payload, ensure_ascii=False).encode("utf-8")
        self.send_response(status)
        self._send_common_headers()
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def _send_file(self, path: Path, content_type: str):
        body = path.read_bytes()
        self.send_response(200)
        self._send_common_headers()
        self.send_header("Content-Type", content_type)
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def _send_frontend_asset(self, path: str):
        asset_path = _resolve_frontend_asset(self.app.static_root, path)
        self._send_file(asset_path, _content_type_for_path(asset_path))

    def _send_common_headers(self):
        self.send_header("Access-Control-Allow-Origin", "*")
        self.send_header(
            "Access-Control-Allow-Methods",
            "GET, POST, PUT, DELETE, OPTIONS",
        )
        self.send_header("Access-Control-Allow-Headers", "Content-Type")


def normalize_job_options(command: str, payload: Dict[str, Any]) -> Dict[str, Any]:
    options = {}
    raw_options = payload.get("options", {})
    if raw_options is None:
        raw_options = {}
    if not isinstance(raw_options, dict):
        raise ApiError(
            400,
            "invalid_request",
            "`options` must be an object",
            field="options",
        )

    options.update(raw_options)
    for key, value in payload.items():
        if key in {"text", "preset", "options", "render"}:
            continue
        options[key] = value

    aliases = {
        "textDensity": "text_density",
        "fontSize": "size",
        "padY": "pad_y",
        "lineSpacing": "line_spacing",
        "cropAlign": "crop_align",
    }
    for source, target in aliases.items():
        if source in options and target not in options:
            options[target] = options.pop(source)

    normalized = {}
    for key, value in options.items():
        if key not in _allowed_options(command):
            raise ApiError(
                422,
                "invalid_option",
                f"Unsupported option for {command}: {key}",
                field=key,
            )
        normalized[key] = validate_job_option(command, key, value)

    return normalized


def validate_job_option(command: str, key: str, value: Any) -> Any:
    if key in {"brightness", "contrast", "gamma"}:
        return _positive_number(key, value)
    if key == "method":
        return _choice(key, value, {"fs", "ordered", "th"})
    if key == "feed":
        return _int_range(key, value, minimum=0)
    if key == "repeat":
        return _int_range(key, value, minimum=1)
    if key == "preview":
        return _bool_value(key, value)

    if command == "text":
        if key == "size":
            return _int_range(key, value, minimum=1)
        if key == "pad_y":
            return _int_range(key, value, minimum=0)
        if key == "line_spacing":
            return _number_range(key, value, minimum=0)
        if key == "align":
            return _choice(key, value, {"left", "center", "right"})
        if key == "text_density":
            return _choice(key, value, {"light", "normal", "dark"})

    if command == "img":
        if key == "rotate":
            return _choice(key, value, {0, 90, 180, 270})
        if key == "crop":
            return _crop_value(value)
        if key == "fit":
            return _choice(
                key,
                value,
                {"width", "contain", "cover", "stretch", "none", "autofit"},
            )
        if key == "height":
            return None if value is None else _int_range(key, value, minimum=1)
        if key == "crop_align":
            return _choice(key, value, {"top", "center", "bottom"})
        if key == "invert":
            return _bool_value(key, value)
        if key == "threshold":
            return (
                None
                if value is None
                else _int_range(key, value, minimum=0, maximum=255)
            )

    raise ApiError(
        422,
        "invalid_option",
        f"Unsupported option for {command}: {key}",
        field=key,
    )


def runtime_settings_from_snapshot(data: Dict[str, Any]) -> RuntimeSettings:
    image = dict(data["image"])
    if image.get("crop") is not None:
        image["crop"] = tuple(image["crop"])

    return RuntimeSettings(
        device=DeviceSettings(**data["device"]),
        printer=PrinterSettings(**data["printer"]),
        render=RenderSettings(**data["render"]),
        text=TextSettings(**data["text"]),
        image=ImageSettings(**image),
        preview=data.get("preview", False),
        preset=data.get("preset"),
    )


def coerce_form_value(value: str) -> Any:
    stripped = value.strip()
    if stripped.lower() == "true":
        return True
    if stripped.lower() == "false":
        return False
    if stripped.lower() == "null":
        return None
    if stripped.startswith(("{", "[")):
        try:
            return json.loads(stripped)
        except json.JSONDecodeError:
            return value
    try:
        return int(stripped)
    except ValueError:
        pass
    try:
        return float(stripped)
    except ValueError:
        return value


def create_server(
    *,
    host: str = DEFAULT_HOST,
    port: int = DEFAULT_PORT,
    project_root: str | Path = ".",
    config_path: Optional[str | Path] = None,
    data_root: Optional[str | Path] = None,
    static_root: Optional[str | Path] = None,
    server_service: str = DEFAULT_SERVER_SERVICE,
) -> KotPrinterHTTPServer:
    app = KotPrinterServer(
        project_root=project_root,
        config_path=config_path,
        data_root=data_root,
        static_root=static_root,
        server_host=host,
        server_port=port,
        server_service=server_service,
    )
    httpd = KotPrinterHTTPServer((host, port), KotPrinterRequestHandler, app)
    httpd.app.server_port = httpd.server_address[1]
    return httpd


def main(argv=None):
    parser = argparse.ArgumentParser(prog="kotprinter-server")
    parser.add_argument("--host", default=DEFAULT_HOST)
    parser.add_argument("--port", type=int, default=DEFAULT_PORT)
    parser.add_argument("--project-root", default=os.getcwd())
    parser.add_argument("--config")
    parser.add_argument("--data-root")
    parser.add_argument(
        "--server-service",
        default=DEFAULT_SERVER_SERVICE,
        help="systemd service name expected by diagnostics",
    )
    parser.add_argument(
        "--static-root",
        help="frontend build directory, defaults to PROJECT_ROOT/web/dist",
    )
    args = parser.parse_args(argv)

    httpd = create_server(
        host=args.host,
        port=args.port,
        project_root=args.project_root,
        config_path=args.config,
        data_root=args.data_root,
        static_root=args.static_root,
        server_service=args.server_service,
    )
    host, port = httpd.server_address
    print(f"kotPrinter serving on http://{host}:{port}")
    print("API namespace: /api")
    print(f"Frontend static root: {httpd.app.static_root}")
    try:
        httpd.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        httpd.server_close()
    return 0


def _allowed_options(command: str) -> set[str]:
    common = {"method", "brightness", "contrast", "gamma", "feed", "repeat", "preview"}
    if command == "text":
        return common | {"size", "pad_y", "line_spacing", "align", "text_density"}
    if command == "img":
        return common | {
            "rotate",
            "crop",
            "fit",
            "height",
            "crop_align",
            "invert",
            "threshold",
        }
    return common


def _positive_number(field: str, value: Any) -> float:
    return _number_range(field, value, minimum=0, exclusive=True)


def _number_range(
    field: str,
    value: Any,
    *,
    minimum: Optional[float] = None,
    exclusive: bool = False,
) -> float:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise ApiError(422, "invalid_option", f"{field} must be a number", field=field)
    if minimum is None:
        return value
    if exclusive and value <= minimum:
        raise ApiError(
            422,
            "invalid_option",
            f"{field} must be greater than {minimum}",
            field=field,
        )
    if not exclusive and value < minimum:
        raise ApiError(
            422,
            "invalid_option",
            f"{field} must be {minimum} or greater",
            field=field,
        )
    return value


def _int_range(
    field: str,
    value: Any,
    *,
    minimum: Optional[int] = None,
    maximum: Optional[int] = None,
) -> int:
    if isinstance(value, bool) or not isinstance(value, int):
        raise ApiError(
            422,
            "invalid_option",
            f"{field} must be an integer",
            field=field,
        )
    if minimum is not None and value < minimum:
        raise ApiError(
            422,
            "invalid_option",
            f"{field} must be {minimum} or greater",
            field=field,
        )
    if maximum is not None and value > maximum:
        raise ApiError(
            422,
            "invalid_option",
            f"{field} must be {maximum} or less",
            field=field,
        )
    return value


def _bool_value(field: str, value: Any) -> bool:
    if not isinstance(value, bool):
        raise ApiError(
            422,
            "invalid_option",
            f"{field} must be true or false",
            field=field,
        )
    return value


def _choice(field: str, value: Any, choices: set[Any]) -> Any:
    if value not in choices:
        choices_text = ", ".join(str(choice) for choice in sorted(choices))
        raise ApiError(
            422,
            "invalid_option",
            f"{field} must be one of: {choices_text}",
            field=field,
        )
    return value


def _crop_value(value: Any):
    if isinstance(value, str):
        parts = value.split(",")
    elif isinstance(value, (list, tuple)):
        parts = value
    else:
        raise ApiError(
            422,
            "invalid_option",
            "crop must be left,top,width,height",
            field="crop",
        )

    if len(parts) != 4:
        raise ApiError(
            422,
            "invalid_option",
            "crop must be left,top,width,height",
            field="crop",
        )

    try:
        left, top, width, height = [int(part) for part in parts]
    except (TypeError, ValueError) as e:
        raise ApiError(
            422,
            "invalid_option",
            "crop values must be integers",
            field="crop",
        ) from e

    if left < 0 or top < 0:
        raise ApiError(
            422,
            "invalid_option",
            "crop left and top must be 0 or greater",
            field="crop",
        )
    if width <= 0 or height <= 0:
        raise ApiError(
            422,
            "invalid_option",
            "crop width and height must be greater than 0",
            field="crop",
        )

    return (left, top, width, height)


def _parse_options_json(value: str) -> Dict[str, Any]:
    try:
        parsed = json.loads(value)
    except json.JSONDecodeError as e:
        raise ApiError(
            400,
            "invalid_options_json",
            "`options` must be valid JSON",
        ) from e
    if not isinstance(parsed, dict):
        raise ApiError(400, "invalid_options_json", "`options` must be a JSON object")
    return parsed


def _require_object_payload(payload: Any) -> Dict[str, Any]:
    if not isinstance(payload, dict):
        raise ApiError(
            400,
            "invalid_request",
            "Request body must be a JSON object",
        )
    return payload


def _validate_history_cleanup_overrides(payload: Dict[str, Any]) -> Dict[str, Any]:
    allowed = {"enabled", "retentionDays"}
    overrides = {}
    for key, value in payload.items():
        if key not in allowed:
            raise ApiError(
                422,
                "invalid_history_option",
                f"Unsupported history cleanup option: {key}",
                field=key,
            )
        if key == "enabled":
            if not isinstance(value, bool):
                raise ApiError(
                    422,
                    "invalid_history_option",
                    "enabled must be true or false",
                    field=key,
                )
            overrides[key] = value
        if key == "retentionDays":
            if value is None:
                overrides[key] = None
            else:
                overrides[key] = _int_range(key, value, minimum=0)
    return overrides


def _query_int(query: Dict[str, list[str]], key: str) -> Optional[int]:
    values = query.get(key)
    if not values:
        return None
    try:
        value = int(values[-1])
    except ValueError as e:
        raise ApiError(
            400,
            "invalid_query",
            f"{key} must be an integer",
            field=key,
        ) from e
    if value < 1:
        raise ApiError(400, "invalid_query", f"{key} must be 1 or greater", field=key)
    return value


def _content_type_for_path(path: Path) -> str:
    content_type, _ = mimetypes.guess_type(str(path))
    if content_type:
        return content_type
    if path.suffix.lower() == ".txt":
        return "text/plain; charset=utf-8"
    return "application/octet-stream"


def _is_api_path(path: str) -> bool:
    return path == "/api" or path.startswith("/api/")


def _resolve_frontend_asset(static_root: Path, request_path: str) -> Path:
    index_path = static_root / FRONTEND_INDEX_FILE
    if not index_path.is_file():
        raise ApiError(
            404,
            "frontend_not_built",
            "Frontend build not found. Run `npm run build` in web/ before "
            "serving the UI.",
            details={"staticRoot": str(static_root)},
        )

    relative_path = unquote(request_path).lstrip("/")
    if not relative_path:
        return index_path

    candidate = (static_root / relative_path).resolve()
    try:
        candidate.relative_to(static_root)
    except ValueError as e:
        raise ApiError(
            403,
            "invalid_static_path",
            "Invalid frontend asset path",
        ) from e

    if candidate.is_file():
        return candidate

    if relative_path == "assets" or relative_path.startswith("assets/"):
        raise ApiError(
            404,
            "static_asset_not_found",
            f"Frontend asset not found: /{relative_path}",
        )

    if Path(relative_path).suffix:
        raise ApiError(
            404,
            "static_asset_not_found",
            f"Frontend asset not found: /{relative_path}",
        )

    return index_path


def _queue_entry_dict(
    entry: Optional[QueueEntry],
    *,
    status: Optional[str] = None,
) -> Optional[Dict[str, Any]]:
    if entry is None:
        return None

    data = entry.as_dict()
    if status is not None:
        data["status"] = status
    return data


def _transport_error_dict(
    error: TransportError,
    *,
    queue_id: str,
) -> Dict[str, Any]:
    return {
        "code": "print_failed",
        "message": str(error),
        "partial": _is_partial_transport_error(error),
        "queueId": queue_id,
    }


def _is_partial_transport_error(error: TransportError) -> bool:
    return isinstance(error, TransportWriteError) and error.partial


if __name__ == "__main__":
    raise SystemExit(main())
