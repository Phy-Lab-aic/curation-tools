"""Mockup test: exercises backend services directly against the mock dataset."""

import asyncio
import sys
from pathlib import Path

# Ensure the project root is on sys.path so 'backend' is importable
PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROJECT_ROOT))

from backend.services.dataset_service import DatasetService
from backend.services.episode_service import EpisodeService
from backend.services import task_service
import pyarrow.parquet as pq

MOCK_DATASET = Path(__file__).parent / "mock_dataset"


def reset_mock_dataset() -> None:
    """Recreate the mock dataset from scratch so tests are idempotent."""
    from tests.create_mock_dataset import create_tasks_parquet, create_episodes_parquet, create_data_parquet
    create_tasks_parquet()
    create_episodes_parquet()
    create_data_parquet()


def make_services() -> tuple[DatasetService, EpisodeService]:
    """Create fresh service instances pointing at the mock dataset."""
    ds = DatasetService()
    ds.load_dataset(MOCK_DATASET)

    # Patch the module-level singleton used by episode_service and task_service
    import backend.services.dataset_service as ds_mod
    import backend.services.episode_service as ep_mod
    import backend.services.task_service as ts_mod

    ds_mod.dataset_service = ds
    ep_mod.dataset_service = ds
    ts_mod.dataset_service = ds

    es = EpisodeService()
    return ds, es


async def run_tests() -> None:
    reset_mock_dataset()
    ds, es = make_services()

    # --- get_info ---
    info = ds.get_info()
    assert info["fps"] == 30, f"Expected fps=30, got {info['fps']}"
    assert info["total_episodes"] == 5, f"Expected total_episodes=5, got {info['total_episodes']}"
    assert info["total_tasks"] == 2, f"Expected total_tasks=2, got {info['total_tasks']}"
    assert info["robot_type"] == "mock_robot"
    print("PASS: get_info() returns correct metadata")

    # --- get_episodes ---
    episodes = await es.get_episodes()
    assert len(episodes) == 5, f"Expected 5 episodes, got {len(episodes)}"
    ep_indices = sorted(e["episode_index"] for e in episodes)
    assert ep_indices == [0, 1, 2, 3, 4], f"Unexpected episode indices: {ep_indices}"
    print("PASS: get_episodes() returns 5 episodes")

    # --- get_tasks ---
    tasks = task_service.get_tasks()
    assert len(tasks) == 2, f"Expected 2 tasks, got {len(tasks)}"
    task_instructions = {t["task_index"]: t["task_instruction"] for t in tasks}
    assert task_instructions[0] == "Pick up the red cube", f"Unexpected task 0: {task_instructions[0]}"
    assert task_instructions[1] == "Place the cube on the plate", f"Unexpected task 1: {task_instructions[1]}"
    print("PASS: get_tasks() returns 2 tasks with correct instructions")

    # --- update_episode 0 with grade="A" and tags=["good", "clean"] ---
    updated = await es.update_episode(episode_index=0, grade="A", tags=["good", "clean"])
    assert updated["grade"] == "A", f"Expected grade='A', got {updated['grade']}"
    assert updated["tags"] == ["good", "clean"], f"Unexpected tags: {updated['tags']}"
    print("PASS: update_episode() returns updated record with grade and tags")

    # Verify persistence: re-read directly from parquet
    ep_file = MOCK_DATASET / "meta" / "episodes" / "chunk-000" / "file-000.parquet"
    table = pq.read_table(ep_file)
    ep_indices_col = table.column("episode_index").to_pylist()
    row_pos = ep_indices_col.index(0)
    persisted_grade = table.column("grade").to_pylist()[row_pos]
    persisted_tags = table.column("tags").to_pylist()[row_pos]
    assert persisted_grade == "A", f"Persisted grade mismatch: {persisted_grade}"
    assert persisted_tags == ["good", "clean"], f"Persisted tags mismatch: {persisted_tags}"
    print("PASS: Episode update persisted correctly to parquet")

    # --- update_task 0 instruction ---
    new_instruction = "Pick up the blue cube"
    result = await task_service.update_task(task_index=0, task_instruction=new_instruction)
    assert result["task_instruction"] == new_instruction, f"Unexpected result: {result}"
    print("PASS: update_task() returns updated task")

    # Verify persistence: re-read tasks.parquet directly
    tasks_file = MOCK_DATASET / "meta" / "tasks.parquet"
    tasks_table = pq.read_table(tasks_file)
    task_idx_col = tasks_table.column("task_index").to_pylist()
    task_row_pos = task_idx_col.index(0)
    persisted_task = tasks_table.column("task").to_pylist()[task_row_pos]
    assert persisted_task == new_instruction, f"Persisted task mismatch: {persisted_task}"
    print("PASS: Task update persisted correctly to parquet")

    print()
    print("ALL TESTS PASSED")


if __name__ == "__main__":
    asyncio.run(run_tests())
