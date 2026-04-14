export const GRADES = ['good', 'normal', 'bad'] as const
export type Grade = (typeof GRADES)[number]

// Removed: GRADE_COLORS (replaced by CSS variables --c-green/--c-yellow/--c-red)

export interface DatasetInfo {
  path: string
  name: string
  fps: number
  total_episodes: number
  total_tasks: number
  robot_type: string | null
  features: Record<string, unknown>
}

export interface Episode {
  episode_index: number
  length: number
  task_index: number
  task_instruction: string
  chunk_index: number
  file_index: number
  dataset_from_index: number
  dataset_to_index: number
  grade: string | null
  tags: string[]
}

export interface Task {
  task_index: number
  task_instruction: string
}

export interface EpisodeUpdate {
  grade: string | null
  tags: string[]
}

export interface TaskUpdate {
  task_instruction: string
}

// ── New types for 3-level navigation ──────────────

export interface CellInfo {
  name: string        // "cell001"
  path: string        // "/tmp/hf-mounts/Phy-lab/dataset/cell001"
  mount_root: string  // "/tmp/hf-mounts/Phy-lab/dataset"
  dataset_count: number
  active: boolean     // mount path is accessible
}

export interface DatasetSummary {
  name: string
  path: string
  total_episodes: number
  graded_count: number
  robot_type: string | null
  fps: number
}

export type DatasetTab = 'overview' | 'curate' | 'fields' | 'ops'

export type AppState =
  | { view: 'library' }
  | { view: 'cell'; cellName: string; cellPath: string }
  | { view: 'dataset'; cellName: string; cellPath: string; datasetPath: string; datasetName: string; tab: DatasetTab }
