"""Persistent, fail-closed accounting for newly transferred V2 payload bytes."""

from __future__ import annotations

import json
import os
from pathlib import Path
from threading import RLock


class DownloadLimitReached(RuntimeError):
    """The next complete payload cannot fit within the configured cap."""


class ByteBudget:
    def __init__(self, root: str | Path, limit_bytes: int, profile_id: str):
        self.root = Path(root)
        self.limit_bytes = int(limit_bytes)
        self.profile_id = profile_id
        self._accounting_lock = RLock()
        self.root.mkdir(parents=True, exist_ok=True)
        self.ledger_path = self.root / ".download_budget.json"
        self.lock_path = self.root / ".download_budget.lock"
        self._lock_handle = self.lock_path.open("a+b")
        try:
            if os.name == "nt":
                import msvcrt
                self._lock_handle.seek(0)
                self._lock_handle.write(b"0")
                self._lock_handle.flush()
                self._lock_handle.seek(0)
                msvcrt.locking(self._lock_handle.fileno(), msvcrt.LK_NBLCK, 1)
            else:
                import fcntl
                fcntl.flock(self._lock_handle.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
        except OSError as error:
            self._lock_handle.close()
            raise RuntimeError("Another process is using the recommended acquisition budget") from error
        try:
            if self.ledger_path.exists():
                ledger = json.loads(self.ledger_path.read_text(encoding="utf-8"))
                if ledger.get("profile_id") != profile_id or ledger.get("limit_bytes") != limit_bytes:
                    raise ValueError("Existing byte ledger belongs to a different profile or cap")
                self.downloaded_bytes = int(ledger["downloaded_bytes"])
                self.charged_bytes = int(ledger["charged_bytes"])
                if not 0 <= self.downloaded_bytes <= self.charged_bytes <= limit_bytes:
                    raise ValueError("Invalid persisted byte count")
            else:
                existing = [path for path in self.root.rglob("*") if path.is_file() and path != self.lock_path]
                if existing:
                    raise ValueError("Unmetered files exist in the recommended cache; refusing to start a new ledger")
                self.downloaded_bytes = 0
                self.charged_bytes = 0
                self._persist()
        except BaseException:
            self.close()
            raise

    def _persist(self) -> None:
        temporary = self.ledger_path.with_suffix(".json.tmp")
        with temporary.open("w", encoding="utf-8") as handle:
            json.dump({"profile_id": self.profile_id, "limit_bytes": self.limit_bytes,
                       "downloaded_bytes": self.downloaded_bytes,
                       "charged_bytes": self.charged_bytes}, handle)
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(temporary, self.ledger_path)

    @property
    def remaining_bytes(self) -> int:
        return self.limit_bytes - self.charged_bytes

    def ensure_capacity(self, expected_bytes: int) -> None:
        with self._accounting_lock:
            if expected_bytes < 0:
                raise ValueError("Expected payload length cannot be negative")
            if expected_bytes > self.remaining_bytes:
                raise DownloadLimitReached(
                    f"8 GiB payload cap reached: {self.downloaded_bytes / 2**30:.3f} GiB used; "
                    f"next complete payload needs {expected_bytes / 2**20:.3f} MiB"
                )

    def reserve_transfer(self, expected_bytes: int) -> None:
        """Charge the entire HTTP payload before network I/O; retries charge again."""
        with self._accounting_lock:
            self.ensure_capacity(expected_bytes)
            self.charged_bytes += expected_bytes
            self._persist()

    def consume(self, count: int) -> None:
        with self._accounting_lock:
            if count < 0 or self.downloaded_bytes + count > self.charged_bytes:
                raise ValueError("Payload exceeded its reserved byte budget")
            # Persist observed bytes before writing. Charged bytes, persisted before
            # the request, remain the hard ceiling even across a process crash.
            self.downloaded_bytes += count
            self._persist()

    def close(self) -> None:
        handle = getattr(self, "_lock_handle", None)
        if handle is not None and not handle.closed:
            if os.name == "nt":
                import msvcrt
                handle.seek(0)
                msvcrt.locking(handle.fileno(), msvcrt.LK_UNLCK, 1)
            else:
                import fcntl
                fcntl.flock(handle.fileno(), fcntl.LOCK_UN)
            handle.close()

    def __enter__(self) -> "ByteBudget":
        return self

    def __exit__(self, *_: object) -> None:
        self.close()
