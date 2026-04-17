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
  reason: string | null
  created_at: string | null
}

export interface Task {
  task_index: number
  task_instruction: string
}

export interface EpisodeUpdate {
  grade: string | null
  tags: string[]
  reason?: string | null
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
  good_count: number
  normal_count: number
  bad_count: number
  robot_type: string | null
  fps: number
  total_duration_sec: number
  good_duration_sec: number
  normal_duration_sec: number
  bad_duration_sec: number
}

export type DatasetTab = 'overview' | 'curate' | 'fields'

export interface CurateFilter {
  grade?: string
  lengthRange?: [number, number]
  tag?: string
}

export type AppState =
  | { view: 'library' }
  | { view: 'cell'; cellName: string; cellPath: string }
  | { view: 'dataset'; cellName: string; cellPath: string; datasetPath: string; datasetName: string; tab: DatasetTab; filter?: CurateFilter }
  | { view: 'converter' }

// ── Converter types ────────────────────────────

export type ConverterState = 'running' | 'stopped' | 'building' | 'error' | 'unknown'

export interface ConverterTaskProgress {
  cell_task: string
  total: number
  done: number
  pending: number
  failed: number
  retry: number
}

export interface ConverterStatus {
  container_state: ConverterState
  docker_available: boolean
  tasks: ConverterTaskProgress[]
  summary: string
}

export type LogEventType = 'converted' | 'failed' | 'converting' | 'scan' | 'warning' | 'info' | 'error'

export interface LogEvent {
  type: LogEventType
  ts: string
  recording?: string
  frames?: number
  duration?: number
  error_code?: string
  reason?: string
  task?: string
  count?: number
  tasks?: number
  pending?: number
  message?: string
}

// ── Distribution types ──────────────────────────

export interface FieldInfo {
  name: string
  dtype: string
  is_system: boolean
}

export interface DistributionBin {
  label: string
  count: number
}

export interface DistributionResult {
  field: string
  dtype: string
  chart_type: 'histogram' | 'bar'
  bins: DistributionBin[]
  total: number
}

// ── Fields tab types ────────────────────────────

export interface InfoField {
  key: string
  value: unknown
  dtype: string
  is_system: boolean
}

export interface EpisodeColumn {
  name: string
  dtype: string
  is_system: boolean
}
