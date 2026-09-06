from __future__ import annotations

import queue
import threading
import uuid
from dataclasses import dataclass
from datetime import datetime
from typing import Any, Callable, Dict, Optional


QUEUE_STATUS_QUEUED = "queued"
QUEUE_STATUS_PRINTING = "printing"
QUEUE_STATUS_DONE = "done"
QUEUE_STATUS_FAILED = "failed"
QUEUE_STATUS_CANCELED = "canceled"

ACTIVE_QUEUE_STATUSES = {QUEUE_STATUS_QUEUED, QUEUE_STATUS_PRINTING}


class PrintQueueError(Exception):
    pass


@dataclass
class QueueEntry:
    queue_id: str
    job_id: str
    action: str
    status: str
    enqueued_at: str
    started_at: Optional[str] = None
    finished_at: Optional[str] = None
    cancel_requested_at: Optional[str] = None
    result: Optional[Dict[str, Any]] = None
    error: Optional[Dict[str, Any]] = None

    def as_dict(self) -> Dict[str, Any]:
        return {
            "queueId": self.queue_id,
            "jobId": self.job_id,
            "action": self.action,
            "status": self.status,
            "enqueuedAt": self.enqueued_at,
            "startedAt": self.started_at,
            "finishedAt": self.finished_at,
            "cancelRequestedAt": self.cancel_requested_at,
            "result": self.result,
            "error": self.error,
        }


class PrintQueue:
    def __init__(self, worker: Callable[[QueueEntry], Dict[str, Any]]):
        self._worker = worker
        self._queue: queue.Queue[str] = queue.Queue()
        self._entries: Dict[str, QueueEntry] = {}
        self._lock = threading.RLock()
        self._thread = threading.Thread(target=self._run, daemon=True)
        self._thread.start()

    def enqueue(self, job_id: str, action: str, *, submit: bool = True) -> QueueEntry:
        with self._lock:
            active = self.active_entry_for_job(job_id)
            if active is not None:
                raise PrintQueueError(
                    f"Job {job_id} is already {active.status} in the print queue"
                )

            entry = QueueEntry(
                queue_id=uuid.uuid4().hex,
                job_id=job_id,
                action=action,
                status=QUEUE_STATUS_QUEUED,
                enqueued_at=_now(),
            )
            self._entries[entry.queue_id] = entry

        if submit:
            self.submit(entry)
        return entry

    def submit(self, entry: QueueEntry) -> None:
        self._queue.put(entry.queue_id)

    def discard_unsubmitted(self, entry: QueueEntry) -> None:
        with self._lock:
            current = self._entries.get(entry.queue_id)
            if current is not None and current.status == QUEUE_STATUS_QUEUED:
                del self._entries[entry.queue_id]

    def active_entry_for_job(self, job_id: str) -> Optional[QueueEntry]:
        with self._lock:
            for entry in reversed(list(self._entries.values())):
                if entry.job_id == job_id and entry.status in ACTIVE_QUEUE_STATUSES:
                    return entry
        return None

    def latest_entry_for_job(self, job_id: str) -> Optional[QueueEntry]:
        with self._lock:
            for entry in reversed(list(self._entries.values())):
                if entry.job_id == job_id:
                    return entry
        return None

    def cancel_job(self, job_id: str) -> tuple[str, Optional[QueueEntry]]:
        with self._lock:
            entry = self.active_entry_for_job(job_id)
            if entry is None:
                return "not_found", None

            if entry.status == QUEUE_STATUS_QUEUED:
                entry.status = QUEUE_STATUS_CANCELED
                entry.finished_at = _now()
                entry.error = {
                    "code": "job_canceled",
                    "message": "Job was canceled before printing started",
                    "queueId": entry.queue_id,
                }
                return "canceled", entry

            entry.cancel_requested_at = _now()
            return "printing", entry

    def snapshot(self) -> Dict[str, Any]:
        with self._lock:
            entries = [entry.as_dict() for entry in self._entries.values()]

        active = [
            entry
            for entry in entries
            if entry["status"] in ACTIVE_QUEUE_STATUSES
        ]
        return {
            "activeCount": len(active),
            "queuedCount": sum(
                1 for entry in entries if entry["status"] == QUEUE_STATUS_QUEUED
            ),
            "printingCount": sum(
                1 for entry in entries if entry["status"] == QUEUE_STATUS_PRINTING
            ),
            "entries": entries,
        }

    def _run(self) -> None:
        while True:
            queue_id = self._queue.get()
            try:
                entry = self._start(queue_id)
                if entry is None:
                    continue

                try:
                    result = self._worker(entry)
                except Exception as e:
                    self._fail(queue_id, e)
                else:
                    self._complete(queue_id, result)
            finally:
                self._queue.task_done()

    def _start(self, queue_id: str) -> Optional[QueueEntry]:
        with self._lock:
            entry = self._entries.get(queue_id)
            if entry is None or entry.status == QUEUE_STATUS_CANCELED:
                return None

            entry.status = QUEUE_STATUS_PRINTING
            entry.started_at = _now()
            return entry

    def _complete(self, queue_id: str, result: Dict[str, Any]) -> None:
        with self._lock:
            entry = self._entries[queue_id]
            entry.status = QUEUE_STATUS_DONE
            entry.finished_at = _now()
            entry.result = result

    def _fail(self, queue_id: str, error: Exception) -> None:
        with self._lock:
            entry = self._entries[queue_id]
            entry.status = QUEUE_STATUS_FAILED
            entry.finished_at = _now()
            entry.error = {
                "code": error.__class__.__name__,
                "message": str(error),
                "queueId": queue_id,
            }


def _now() -> str:
    return datetime.now().astimezone().isoformat()
