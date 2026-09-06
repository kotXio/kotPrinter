from __future__ import annotations

import json
import os
import shutil
import uuid
from dataclasses import asdict, dataclass
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any, Dict, Iterable, List, Optional

from .core import ImageJob, RenderResult, RuntimeSettings, TextJob


JOB_SCHEMA_VERSION = 1

STATUS_DRAFT = "draft"
STATUS_QUEUED = "queued"
STATUS_RENDERED = "rendered"
STATUS_PRINTING = "printing"
STATUS_DONE = "done"
STATUS_FAILED = "failed"
STATUS_CANCELED = "canceled"
ACTIVE_STATUSES = {STATUS_QUEUED, STATUS_PRINTING, "rendering"}


class JobStoreError(Exception):
    pass


class JobNotFoundError(JobStoreError):
    pass


@dataclass(frozen=True)
class StoredJob:
    job_id: str
    job_type: str
    status: str
    job_dir: Path
    job_path: Path
    source_path: Path
    preview_path: Optional[Path] = None
    raster_path: Optional[Path] = None


class JobStore:
    def __init__(self, root: str | Path = "data"):
        self.root = Path(root)
        self.history_dir = self.root / "history"
        self.index_path = self.history_dir / "index.jsonl"

    def create_text_job(
        self,
        job: TextJob,
        render_result: Optional[RenderResult] = None,
    ) -> StoredJob:
        stored = self._create_job_shell("text")
        source_path = stored.job_dir / "source.txt"
        _write_text(source_path, job.text)

        record = self._base_record(
            stored,
            settings=job.settings,
            source_file=source_path.name,
        )
        record["text"] = {
            "length": len(job.text),
        }

        return self._finalize_job(stored, record, render_result)

    def create_image_job(
        self,
        job: ImageJob,
        render_result: Optional[RenderResult] = None,
    ) -> StoredJob:
        source = Path(job.path)
        if not source.exists():
            raise JobStoreError(f"Image source does not exist: {source}")

        stored = self._create_job_shell("image")
        source_name = _source_image_name(source)
        source_path = stored.job_dir / source_name
        shutil.copy2(source, source_path)

        record = self._base_record(
            stored,
            settings=job.settings,
            source_file=source_path.name,
        )
        record["image"] = {
            "originalPath": str(source),
            "storedSource": source_path.name,
        }

        return self._finalize_job(stored, record, render_result)

    def get_job(self, job_id: str) -> Dict[str, Any]:
        job_path = self._find_job_path(job_id)
        if job_path is None:
            raise JobNotFoundError(f"Job not found: {job_id}")
        return _read_json(job_path)

    def get_preview_path(self, job_id: str) -> Path:
        return self.get_artifact_path(job_id, "preview")

    def get_source_path(self, job_id: str) -> Path:
        record = self.get_job(job_id)
        source_file = record.get("paths", {}).get("source")
        if not source_file:
            raise JobStoreError(f"Job has no source artifact: {job_id}")

        path = Path(record["paths"]["jobDir"]) / source_file
        if not path.exists():
            raise JobStoreError(f"Source artifact is missing: {path}")
        return path

    def get_raster_path(self, job_id: str) -> Path:
        return self.get_artifact_path(job_id, "raster")

    def get_artifact_path(self, job_id: str, artifact: str) -> Path:
        record = self.get_job(job_id)
        artifact_file = record.get("artifacts", {}).get(artifact)
        if not artifact_file:
            raise JobStoreError(f"Job has no {artifact} artifact: {job_id}")

        path = Path(record["paths"]["jobDir"]) / artifact_file
        if not path.exists():
            raise JobStoreError(f"{artifact} artifact is missing: {path}")
        return path

    def list_jobs(self, limit: Optional[int] = None) -> List[Dict[str, Any]]:
        if not self.index_path.exists():
            return []

        jobs_by_id: Dict[str, Dict[str, Any]] = {}
        with self.index_path.open("r", encoding="utf-8") as index_file:
            for line in index_file:
                line = line.strip()
                if not line:
                    continue
                record = json.loads(line)
                job_id = record.get("jobId")
                if not job_id:
                    continue
                jobs_by_id.pop(job_id, None)
                jobs_by_id[job_id] = record

        jobs = list(jobs_by_id.values())
        if limit is None:
            return jobs
        return jobs[-limit:]

    def update_job(
        self,
        job_id: str,
        *,
        status: Optional[str] = None,
        warnings: Optional[List[str]] = None,
        errors: Optional[List[Any]] = None,
        metadata: Optional[Dict[str, Any]] = None,
    ) -> Dict[str, Any]:
        job_path = self._find_job_path(job_id)
        if job_path is None:
            raise JobNotFoundError(f"Job not found: {job_id}")

        record = _read_json(job_path)
        if status is not None:
            record["status"] = status
        if warnings:
            record.setdefault("warnings", []).extend(warnings)
        if errors:
            record.setdefault("errors", []).extend(errors)
        if metadata:
            record.setdefault("jobMetadata", {}).update(metadata)
        record["updatedAt"] = _now().isoformat()

        _write_json(job_path, record)
        self._append_index(_index_record(record))
        return record

    def delete_job(
        self,
        job_id: str,
        *,
        active_job_ids: Optional[Iterable[str]] = None,
    ) -> Dict[str, Any]:
        active_job_ids = set(active_job_ids or [])
        record = self.get_job(job_id)
        if _is_active_record(record, active_job_ids):
            raise JobStoreError(f"Job is active and cannot be deleted: {job_id}")

        job_dir = Path(record["paths"]["jobDir"])
        if not job_dir.exists():
            raise JobStoreError(f"Job directory is missing: {job_dir}")

        shutil.rmtree(job_dir)
        _remove_empty_parents(job_dir.parent, self.history_dir)
        records = self.rebuild_index()
        return {
            "jobId": job_id,
            "jobDir": str(job_dir),
            "remainingJobs": len(records),
        }

    def cleanup_history(
        self,
        *,
        retention_days: Optional[int],
        enabled: bool = True,
        active_job_ids: Optional[Iterable[str]] = None,
        now: Optional[datetime] = None,
    ) -> Dict[str, Any]:
        if not enabled or retention_days in {None, 0}:
            return {
                "enabled": enabled,
                "retentionDays": retention_days,
                "removed": [],
                "skipped": [],
                "errors": [],
                "rebuiltIndexCount": len(self.rebuild_index()),
            }

        if retention_days < 0:
            raise JobStoreError("retention_days must be 0 or greater")

        current_time = now or _now()
        cutoff = current_time - timedelta(days=retention_days)
        active_job_ids = set(active_job_ids or [])

        removed = []
        skipped = []
        errors = []

        if self.history_dir.exists():
            for job_path in sorted(self.history_dir.glob("*/*/*/*/job.json")):
                try:
                    record = _read_json(job_path)
                    job_id = record["jobId"]
                    if _is_active_record(record, active_job_ids):
                        skipped.append(
                            {
                                "jobId": job_id,
                                "reason": "active",
                                "status": record.get("status"),
                            }
                        )
                        continue

                    created_at = _parse_timestamp(record.get("createdAt"))
                    if created_at is None:
                        skipped.append(
                            {
                                "jobId": job_id,
                                "reason": "unknown-createdAt",
                                "status": record.get("status"),
                            }
                        )
                        continue
                    if created_at >= cutoff:
                        continue

                    job_dir = Path(record["paths"]["jobDir"])
                    shutil.rmtree(job_dir)
                    _remove_empty_parents(job_dir.parent, self.history_dir)
                    removed.append(
                        {
                            "jobId": job_id,
                            "jobDir": str(job_dir),
                            "createdAt": record.get("createdAt"),
                            "status": record.get("status"),
                        }
                    )
                except Exception as e:
                    errors.append(
                        {
                            "jobPath": str(job_path),
                            "message": str(e),
                        }
                    )

        records = self.rebuild_index()
        return {
            "enabled": enabled,
            "retentionDays": retention_days,
            "cutoff": cutoff.isoformat(),
            "removed": removed,
            "skipped": skipped,
            "errors": errors,
            "rebuiltIndexCount": len(records),
        }

    def rebuild_index(self) -> List[Dict[str, Any]]:
        records = []
        if self.history_dir.exists():
            for job_path in sorted(self.history_dir.glob("*/*/*/*/job.json")):
                records.append(_index_record(_read_json(job_path)))

        _ensure_parent(self.index_path)
        tmp_path = self.index_path.with_suffix(".jsonl.tmp")
        with tmp_path.open("w", encoding="utf-8") as index_file:
            for record in records:
                index_file.write(json.dumps(record, sort_keys=True))
                index_file.write("\n")
            index_file.flush()
            os.fsync(index_file.fileno())
        os.replace(tmp_path, self.index_path)
        return records

    def _create_job_shell(self, job_type: str) -> StoredJob:
        now = _now()
        job_id = f"{now.strftime('%Y%m%d-%H%M%S')}-{uuid.uuid4().hex[:8]}"
        job_dir = (
            self.history_dir
            / now.strftime("%Y")
            / now.strftime("%m")
            / now.strftime("%d")
            / job_id
        )
        job_dir.mkdir(parents=True, exist_ok=False)

        return StoredJob(
            job_id=job_id,
            job_type=job_type,
            status=STATUS_DRAFT,
            job_dir=job_dir,
            job_path=job_dir / "job.json",
            source_path=job_dir / ("source.txt" if job_type == "text" else "source"),
        )

    def _base_record(
        self,
        stored: StoredJob,
        *,
        settings: RuntimeSettings,
        source_file: str,
    ) -> Dict[str, Any]:
        timestamp = _now().isoformat()
        return {
            "schemaVersion": JOB_SCHEMA_VERSION,
            "jobId": stored.job_id,
            "type": stored.job_type,
            "status": STATUS_DRAFT,
            "createdAt": timestamp,
            "updatedAt": timestamp,
            "preset": settings.preset,
            "options": _job_options(settings),
            "settings": asdict(settings),
            "paths": {
                "jobDir": str(stored.job_dir),
                "source": source_file,
            },
            "artifacts": {},
            "warnings": [],
            "errors": [],
        }

    def _finalize_job(
        self,
        stored: StoredJob,
        record: Dict[str, Any],
        render_result: Optional[RenderResult],
    ) -> StoredJob:
        preview_path = None
        raster_path = None

        if render_result is not None:
            if not render_result.success or render_result.image is None:
                record["status"] = STATUS_FAILED
                if render_result.error:
                    record["errors"].append(
                        {
                            "code": "render_failed",
                            "message": render_result.error,
                        }
                    )
            else:
                preview_path = stored.job_dir / "preview.png"
                raster_path = stored.job_dir / "raster.png"
                render_result.image.save(preview_path)
                render_result.image.save(raster_path)
                record["status"] = STATUS_RENDERED
                record["artifacts"]["preview"] = preview_path.name
                record["artifacts"]["raster"] = raster_path.name

            record["warnings"].extend(render_result.warnings)
            record["renderMetadata"] = dict(render_result.metadata)

        record["updatedAt"] = _now().isoformat()
        _write_json(stored.job_path, record)
        self._append_index(_index_record(record))

        return StoredJob(
            job_id=stored.job_id,
            job_type=stored.job_type,
            status=record["status"],
            job_dir=stored.job_dir,
            job_path=stored.job_path,
            source_path=stored.job_dir / record["paths"]["source"],
            preview_path=preview_path,
            raster_path=raster_path,
        )

    def _append_index(self, record: Dict[str, Any]) -> None:
        _ensure_parent(self.index_path)
        with self.index_path.open("a", encoding="utf-8") as index_file:
            index_file.write(json.dumps(record, sort_keys=True))
            index_file.write("\n")
            index_file.flush()
            os.fsync(index_file.fileno())

    def _find_job_path(self, job_id: str) -> Optional[Path]:
        for item in self.list_jobs():
            if item.get("jobId") == job_id:
                job_path = Path(item["jobPath"])
                if job_path.exists():
                    return job_path

        matches = list(self.history_dir.glob(f"*/*/*/{job_id}/job.json"))
        if not matches:
            return None
        return matches[0]


def _now() -> datetime:
    return datetime.now().astimezone()


def _source_image_name(path: Path) -> str:
    suffix = path.suffix.lower()
    if not suffix:
        suffix = ".bin"
    return f"source{suffix}"


def _index_record(record: Dict[str, Any]) -> Dict[str, Any]:
    return {
        "jobId": record["jobId"],
        "type": record["type"],
        "status": record["status"],
        "createdAt": record["createdAt"],
        "updatedAt": record["updatedAt"],
        "jobPath": str(Path(record["paths"]["jobDir"]) / "job.json"),
        "previewPath": _artifact_path(record, "preview"),
        "rasterPath": _artifact_path(record, "raster"),
        "sourcePath": str(Path(record["paths"]["jobDir"]) / record["paths"]["source"]),
    }


def _job_options(settings: RuntimeSettings) -> Dict[str, Any]:
    return {
        "preview": settings.preview,
        "feed": settings.printer.feed,
        "repeat": settings.printer.repeat,
        "render": asdict(settings.render),
        "text": asdict(settings.text),
        "image": asdict(settings.image),
    }


def _artifact_path(record: Dict[str, Any], artifact: str) -> Optional[str]:
    artifact_file = record.get("artifacts", {}).get(artifact)
    if not artifact_file:
        return None
    return str(Path(record["paths"]["jobDir"]) / artifact_file)


def _is_active_record(
    record: Dict[str, Any],
    active_job_ids: Iterable[str],
) -> bool:
    job_id = record.get("jobId")
    return job_id in active_job_ids or record.get("status") in ACTIVE_STATUSES


def _parse_timestamp(value: Any) -> Optional[datetime]:
    if not isinstance(value, str):
        return None
    try:
        parsed = datetime.fromisoformat(value)
    except ValueError:
        return None
    if parsed.tzinfo is None:
        parsed = parsed.astimezone()
    return parsed


def _remove_empty_parents(path: Path, stop: Path) -> None:
    path = path.resolve()
    stop = stop.resolve()
    while path != stop and stop in path.parents:
        try:
            path.rmdir()
        except OSError:
            break
        path = path.parent


def _write_json(path: Path, data: Dict[str, Any]) -> None:
    _ensure_parent(path)
    tmp_path = path.with_suffix(path.suffix + ".tmp")
    with tmp_path.open("w", encoding="utf-8") as output:
        json.dump(data, output, indent=2, sort_keys=True)
        output.write("\n")
        output.flush()
        os.fsync(output.fileno())
    os.replace(tmp_path, path)


def _read_json(path: Path) -> Dict[str, Any]:
    with path.open("r", encoding="utf-8") as input_file:
        return json.load(input_file)


def _write_text(path: Path, text: str) -> None:
    _ensure_parent(path)
    with path.open("w", encoding="utf-8") as output:
        output.write(text)
        output.flush()
        os.fsync(output.fileno())


def _ensure_parent(path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
