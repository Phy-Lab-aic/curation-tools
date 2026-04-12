"""Conversion pipeline service: watchdog + job queue + rosbag-to-lerobot integration."""
from __future__ import annotations

import json
import logging
import shutil
import sys
import threading
import uuid
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Literal, Optional
from concurrent.futures import ThreadPoolExecutor

logger = logging.getLogger(__name__)

ROSBAG_SRC = Path("/home/weed/psedulab/rosbag-to-lerobot/src")


def _ensure_rosbag_on_path() -> None:
    rosbag_str = str(ROSBAG_SRC)
    if rosbag_str not in sys.path:
        sys.path.insert(0, rosbag_str)


@dataclass
class ConversionJob:
    id: str
    folder: str
    status: Literal["queued", "converting", "done", "failed"]
    message: str = ""
    created_at: str = field(default_factory=lambda: datetime.now(timezone.utc).isoformat())
    finished_at: Optional[str] = None

    def to_dict(self) -> dict:
        return {
            "id": self.id,
            "folder": self.folder,
            "status": self.status,
            "message": self.message,
            "created_at": self.created_at,
            "finished_at": self.finished_at,
        }


class ConversionService:
    """Manages conversion profiles, job queue, and optional watchdog."""

    MAX_HISTORY = 100

    def __init__(self, profiles_dir: Path | None = None) -> None:
        if profiles_dir is None:
            profiles_dir = Path(__file__).resolve().parents[2] / "conversion_configs"
        self._profiles_dir = Path(profiles_dir)
        self._profiles_dir.mkdir(parents=True, exist_ok=True)

        self._jobs: list[ConversionJob] = []
        self._queued_folders: set[str] = set()  # deduplication
        self._lock = threading.Lock()
        self._executor = ThreadPoolExecutor(max_workers=1)

        self._watching: bool = False
        self._watch_input_path: Optional[str] = None
        self._observer: Any = None  # watchdog Observer

    # ------------------------------------------------------------------
    # Profile CRUD
    # ------------------------------------------------------------------

    def save_profile(self, name: str, data: dict) -> None:
        path = self._profiles_dir / f"{name}.json"
        path.write_text(json.dumps(data, indent=2), encoding="utf-8")

    def load_profile(self, name: str) -> dict:
        path = self._profiles_dir / f"{name}.json"
        if not path.exists():
            raise FileNotFoundError(f"Profile not found: {name}")
        return json.loads(path.read_text(encoding="utf-8"))

    def list_profiles(self) -> list[str]:
        return sorted(p.stem for p in self._profiles_dir.glob("*.json"))

    def delete_profile(self, name: str) -> None:
        path = self._profiles_dir / f"{name}.json"
        if not path.exists():
            raise FileNotFoundError(f"Profile not found: {name}")
        path.unlink()

    # ------------------------------------------------------------------
    # Job management
    # ------------------------------------------------------------------

    def get_jobs(self) -> list[dict]:
        with self._lock:
            return [j.to_dict() for j in self._jobs]

    def _add_job(self, folder: str) -> Optional[ConversionJob]:
        """Create and queue a job for the given folder. Returns None if duplicate."""
        with self._lock:
            if folder in self._queued_folders:
                return None
            job = ConversionJob(id=str(uuid.uuid4()), folder=folder, status="queued")
            self._jobs.append(job)
            self._queued_folders.add(folder)
            # Cap history
            if len(self._jobs) > self.MAX_HISTORY:
                self._jobs = self._jobs[-self.MAX_HISTORY:]
            return job

    def _update_job(self, job_id: str, **kwargs) -> None:
        with self._lock:
            for j in self._jobs:
                if j.id == job_id:
                    for k, v in kwargs.items():
                        setattr(j, k, v)
                    break

    # ------------------------------------------------------------------
    # Conversion execution
    # ------------------------------------------------------------------

    def _run_job(self, job: ConversionJob, profile: dict) -> None:
        """Blocking: runs in ThreadPoolExecutor."""
        _ensure_rosbag_on_path()
        try:
            from main import run_conversion  # noqa: PLC0415
        except ImportError as exc:
            self._update_job(
                job.id,
                status="failed",
                message=f"Cannot import rosbag-to-lerobot: {exc}",
                finished_at=datetime.now(timezone.utc).isoformat(),
            )
            with self._lock:
                self._queued_folders.discard(job.folder)
            return

        self._update_job(job.id, status="converting", message="Starting conversion...")

        input_path = Path(profile.get("input_path", ""))
        output_path = profile.get("output_path", "")
        folder_path = input_path / job.folder

        # Write a temporary config JSON that run_conversion can read
        import tempfile, os
        cfg_for_run = {k: v for k, v in profile.items()
                       if k not in ("input_path", "output_path")}
        cfg_for_run["folders"] = [job.folder]

        with tempfile.NamedTemporaryFile(
            mode="w", suffix=".json", delete=False, encoding="utf-8"
        ) as tmp:
            json.dump(cfg_for_run, tmp)
            tmp_path = tmp.name

        try:
            exit_code = run_conversion(
                config_path=tmp_path,
                input_dir=str(input_path),
                output_dir=output_path,
            )
        except Exception as exc:
            exit_code = 1
            logger.exception("run_conversion raised for folder %s", job.folder)
            self._update_job(
                job.id,
                status="failed",
                message=str(exc),
                finished_at=datetime.now(timezone.utc).isoformat(),
            )
            with self._lock:
                self._queued_folders.discard(job.folder)
            return
        finally:
            os.unlink(tmp_path)

        if exit_code == 0:
            # Move folder to processed/
            processed_dir = input_path / "processed"
            processed_dir.mkdir(exist_ok=True)
            dest = processed_dir / job.folder
            if folder_path.exists():
                shutil.move(str(folder_path), str(dest))
            self._update_job(
                job.id,
                status="done",
                message=f"→ processed/{job.folder}",
                finished_at=datetime.now(timezone.utc).isoformat(),
            )
        else:
            self._update_job(
                job.id,
                status="failed",
                message=f"run_conversion exited with code {exit_code}",
                finished_at=datetime.now(timezone.utc).isoformat(),
            )

        with self._lock:
            self._queued_folders.discard(job.folder)

    def submit_folder(self, folder: str, profile: dict) -> Optional[str]:
        """Queue a folder for conversion. Returns job_id or None if duplicate."""
        job = self._add_job(folder)
        if job is None:
            return None
        self._executor.submit(self._run_job, job, profile)
        return job.id

    # ------------------------------------------------------------------
    # Watch status
    # ------------------------------------------------------------------

    def get_watch_status(self) -> dict:
        return {
            "watching": self._watching,
            "input_path": self._watch_input_path,
        }

    # ------------------------------------------------------------------
    # Watchdog
    # ------------------------------------------------------------------

    def start_watching(self, profile_name: str) -> None:
        if self._watching:
            self.stop_watching()

        profile = self.load_profile(profile_name)
        input_path = Path(profile.get("input_path", ""))
        if not input_path.exists():
            raise ValueError(f"Input path does not exist: {input_path}")

        from watchdog.observers import Observer
        from watchdog.events import FileCreatedEvent, PatternMatchingEventHandler

        svc = self

        class McapHandler(PatternMatchingEventHandler):
            def __init__(self):
                super().__init__(patterns=["*.mcap"], ignore_directories=False)

            def on_created(self, event: FileCreatedEvent):
                folder = Path(event.src_path).parent
                # Skip processed/ subdirectory
                if folder.name == "processed" or "processed" in folder.parts:
                    return
                folder_name = folder.name
                logger.info("Detected new MCAP in folder: %s", folder_name)
                svc.submit_folder(folder_name, profile)

        observer = Observer()
        observer.schedule(McapHandler(), str(input_path), recursive=True)
        observer.start()

        self._observer = observer
        self._watching = True
        self._watch_input_path = str(input_path)
        logger.info("Watching %s for new MCAP files", input_path)

    def stop_watching(self) -> None:
        if self._observer is not None:
            self._observer.stop()
            self._observer.join(timeout=5)
            self._observer = None
        self._watching = False
        self._watch_input_path = None
        logger.info("Stopped watching")

    def shutdown(self) -> None:
        self.stop_watching()
        self._executor.shutdown(wait=False)


conversion_service = ConversionService()
