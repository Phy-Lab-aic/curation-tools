"""Rerun visualization service for LeRobot dataset episodes."""

from __future__ import annotations

import logging
from pathlib import Path

try:
    import numpy as np
    import pyarrow.parquet as pq
    import rerun as rr
    HAS_RERUN = True
except ImportError:
    HAS_RERUN = False
    rr = None  # type: ignore[assignment]
    np = None  # type: ignore[assignment]
    pq = None  # type: ignore[assignment]

from backend.datasets.services.dataset_service import dataset_service

logger = logging.getLogger(__name__)
_RERUN_READY = False


def _resolve_video_fps(feature_meta: dict, dataset_fps: float) -> float:
    """Return the best-known fps for a video feature."""
    for key in ("video_info", "info"):
        video_info = feature_meta.get(key)
        if isinstance(video_info, dict):
            value = video_info.get("video.fps")
            if isinstance(value, (int, float)) and value > 0:
                return float(value)
    return dataset_fps if dataset_fps > 0 else 30.0


def ensure_rerun_ready() -> None:
    """Raise a user-facing error when the Rerun viewer is unavailable."""
    if not HAS_RERUN:
        raise RuntimeError("Rerun viewer is not available")
    if not _RERUN_READY:
        raise RuntimeError("Rerun viewer is not ready")


def init_rerun(grpc_port: int, web_port: int) -> None:
    """Initialize Rerun with gRPC server and web viewer."""
    global _RERUN_READY
    if not HAS_RERUN:
        raise ImportError("rerun package not installed — install with: pip install rerun-sdk")
    rr.init("curation_tools")
    server_uri = rr.serve_grpc(grpc_port=grpc_port)
    rr.serve_web_viewer(open_browser=False, web_port=web_port, connect_to=server_uri)
    _RERUN_READY = True
    logger.info("Rerun initialized — gRPC port %d, web port %d", grpc_port, web_port)


def _extract_video_frames(
    video_path: Path, start_frame: int, num_frames: int
) -> list[np.ndarray]:
    """Extract frames from MP4. Returns list of RGB numpy arrays or empty on failure."""
    try:
        import cv2
        cap = cv2.VideoCapture(str(video_path))
        cap.set(cv2.CAP_PROP_POS_FRAMES, start_frame)
        frames: list[np.ndarray] = []
        for _ in range(num_frames):
            ret, frame = cap.read()
            if not ret:
                break
            frames.append(cv2.cvtColor(frame, cv2.COLOR_BGR2RGB))
        cap.release()
        return frames
    except ImportError:
        return []


def _log_scalar_columns(entity_prefix: str, row: dict, columns: list[str]) -> None:
    """Log numeric columns as Rerun Scalar time-series entities.

    Multi-dimensional arrays (e.g. 6-DOF state) are split into separate
    per-dimension scalar entities so each dimension gets its own timeline.
    """
    for col in columns:
        value = row.get(col)
        if value is None:
            continue
        arr = np.asarray(value, dtype=float).ravel()
        entity = f"{entity_prefix}/{col}"
        if arr.size == 1:
            rr.log(entity, rr.Scalar(float(arr[0])))
        elif arr.size > 1:
            for i, val in enumerate(arr):
                rr.log(f"{entity}/{i}", rr.Scalar(float(val)))


def _resolve_episode_rows(
    df: dict[str, list],
    from_idx: int,
    to_idx: int,
    all_columns: list[str],
) -> list[int]:
    """Return file-local row positions for an episode slice."""
    if not all_columns:
        return []

    row_count = len(df.get(all_columns[0], []))
    if row_count == 0:
        return []

    if "index" in df:
        positions = [
            position
            for position, value in enumerate(df["index"])
            if value is not None and from_idx <= int(value) < to_idx
        ]
        if positions:
            if "frame_index" in df:
                positions.sort(key=lambda pos: int(df["frame_index"][pos]))
            return positions

    start = max(0, min(from_idx, row_count))
    stop = max(start, min(to_idx, row_count))
    return list(range(start, stop))


async def visualize_episode(episode_index: int) -> None:
    """Visualize a single episode in Rerun."""
    import asyncio

    ensure_rerun_ready()
    loc = dataset_service.get_episode_file_location(episode_index)
    dataset_path = Path(dataset_service.get_dataset_path())
    dataset_info = dataset_service.get_info()
    features = dataset_service.get_features()

    from_idx = loc["dataset_from_index"]
    to_idx = loc["dataset_to_index"]
    chunk_idx = loc["data_chunk_index"]
    file_idx = loc["data_file_index"]

    # Clear previous visualization
    rr.log("world", rr.Clear(recursive=True))

    # Read data parquet file
    data_path = dataset_path / f"data/chunk-{chunk_idx:03d}/file-{file_idx:03d}.parquet"
    if not data_path.exists():
        raise FileNotFoundError(f"Data parquet not found: {data_path}")

    table = await asyncio.to_thread(pq.read_table, data_path)
    df = table.to_pydict()
    all_columns = list(df.keys())

    # Classify columns by feature type
    image_columns: list[str] = []
    state_columns: list[str] = []
    action_columns: list[str] = []

    for col, feature in features.items():
        dtype = feature.get("dtype", "")
        if dtype in ("image", "video") or col.startswith("observation.image"):
            image_columns.append(col)
        elif col.startswith("observation.") and col in all_columns:
            state_columns.append(col)
        elif col.startswith("action") and col in all_columns:
            action_columns.append(col)

    # Skip remaining columns — only log explicitly classified observation/action columns
    # to avoid polluting visualizations with metadata like timestamp, index, etc.

    # Per-frame scalar logging
    row_positions = _resolve_episode_rows(df, from_idx, to_idx, all_columns)
    num_frames = len(row_positions) if row_positions else max(0, to_idx - from_idx)
    for sequence, row_position in enumerate(row_positions):
        rr.set_time("frame", sequence=sequence)
        row = {col: df[col][row_position] for col in all_columns if row_position < len(df[col])}
        _log_scalar_columns("observation", row, state_columns)
        _log_scalar_columns("action", row, action_columns)

    # Video frame logging
    video_features = {
        col: meta for col, meta in features.items()
        if meta.get("dtype") == "video"
    }

    for vkey, _meta in video_features.items():
        vid_info = loc.get("videos", {}).get(vkey, {})
        vid_chunk = vid_info.get("chunk_index", chunk_idx)
        vid_file = vid_info.get("file_index", file_idx)
        video_start_ts = float(vid_info.get("from_timestamp") or 0.0)
        video_fps = _resolve_video_fps(_meta, float(dataset_info.get("fps") or 0))
        start_frame = max(0, int(round(video_start_ts * video_fps)))

        video_path = dataset_path / f"videos/{vkey}/chunk-{vid_chunk:03d}/file-{vid_file:03d}.mp4"
        if not video_path.exists():
            logger.warning("Video not found, skipping %s: %s", vkey, video_path)
            continue

        try:
            frames = _extract_video_frames(video_path, start_frame, num_frames)
        except Exception as exc:
            logger.warning("Video extraction failed for %s: %s", vkey, exc)
            continue

        if not frames:
            continue

        entity = f"camera/{vkey.replace('.', '/')}"
        for i, frame_rgb in enumerate(frames):
            rr.set_time("frame", sequence= i)
            rr.log(entity, rr.Image(frame_rgb))

    logger.info("Visualized episode %d (%d frames)", episode_index, num_frames)
