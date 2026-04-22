import { useState, useEffect, useCallback, useRef } from 'react'
import client from '../api/client'
import type { Episode } from '../types/index'

interface TrimPanelProps {
  datasetPath: string | null
  episodes: Episode[]
}

type SyncSummary = {
  mode: string
  created: number
  skipped_duplicates: number
}

interface JobStatus {
  job_id: string
  operation: string
  status: string
  created_at: string
  completed_at: string | null
  error: string | null
  result_path: string | null
  summary?: SyncSummary | null
}

interface StampStatus {
  stamped: boolean
  is_terminal_count_sample: number
}

type TargetMode = 'create' | 'merge'
type Target = { mode: TargetMode; path: string }

interface SummaryResponse {
  path: string
  total_episodes: number
  robot_type: string | null
  fps: number
  features_count: number
}

type TabId = 'out' | 'delete' | 'cycles'

function useJobPoller() {
  const [jobStatus, setJobStatus] = useState<JobStatus | null>(null)
  const [polling, setPolling] = useState(false)

  const startPolling = useCallback((jobId: string) => {
    setPolling(true)
    setJobStatus(null)

    const interval = setInterval(async () => {
      try {
        const resp = await client.get<JobStatus>(`/datasets/ops/status/${jobId}`)
        const s = resp.data
        setJobStatus(s)
        if (s.status === 'complete' || s.status === 'completed' || s.status === 'failed') {
          clearInterval(interval)
          setPolling(false)
        }
      } catch {
        clearInterval(interval)
        setPolling(false)
      }
    }, 1000)

    return () => clearInterval(interval)
  }, [])

  const reset = useCallback(() => {
    setJobStatus(null)
    setPolling(false)
  }, [])

  return { jobStatus, polling, startPolling, reset }
}

function JobProgress({ jobStatus, polling }: { jobStatus: JobStatus | null; polling: boolean }) {
  if (!jobStatus && !polling) return null

  if (polling && !jobStatus) {
    return <div style={s.statusBox}>Running...</div>
  }

  if (!jobStatus) return null

  const isOk = jobStatus.status === 'complete' || jobStatus.status === 'completed'
  const isFail = jobStatus.status === 'failed'

  return (
    <div style={{ ...s.statusBox, borderColor: isOk ? 'var(--c-green)' : isFail ? 'var(--c-red)' : 'var(--interactive)' }}>
      <div style={{ display: 'flex', alignItems: 'center', gap: 6 }}>
        <span style={{ color: isOk ? 'var(--c-green)' : isFail ? 'var(--c-red)' : 'var(--text-muted)', fontSize: 12, fontWeight: 600 }}>
          {jobStatus.status.toUpperCase()}
        </span>
        {polling && <span style={s.spinner}>⟳</span>}
      </div>
      {isOk && jobStatus.result_path && (
        <div style={s.resultPath}>
          Result: <span style={{ fontFamily: 'var(--font-mono)', color: 'var(--c-green)' }}>{jobStatus.result_path}</span>
        </div>
      )}
      {isFail && jobStatus.error && (
        <div style={s.errorText}>{jobStatus.error}</div>
      )}
    </div>
  )
}

type SplitMode = 'grade' | 'tag'

const GRADE_OPTIONS = ['good', 'normal', 'bad', 'Ungraded'] as const

function formatEpisodeRanges(indices: number[]): string {
  if (indices.length === 0) return 'none'
  const sorted = [...indices].sort((a, b) => a - b)
  const ranges: string[] = []
  let start = sorted[0]
  let end = sorted[0]
  for (let i = 1; i < sorted.length; i++) {
    if (sorted[i] === end + 1) {
      end = sorted[i]
    } else {
      ranges.push(start === end ? `${start}` : `${start}-${end}`)
      start = sorted[i]
      end = sorted[i]
    }
  }
  ranges.push(start === end ? `${start}` : `${start}-${end}`)
  return `Episodes: ${ranges.join(', ')}`
}

interface BrowseDirEntry {
  name: string
  path: string
  is_lerobot_dataset: boolean
}

interface BrowseDirsResponse {
  path: string
  parent: string | null
  roots: string[]
  entries: BrowseDirEntry[]
}

function formatSuggestedName(sourceDatasetName: string): string {
  const now = new Date()
  const yyyy = now.getFullYear()
  const mm = String(now.getMonth() + 1).padStart(2, '0')
  const dd = String(now.getDate()).padStart(2, '0')
  return `${sourceDatasetName}__out_${yyyy}${mm}${dd}`
}

function uniqueName(base: string, existing: Set<string>): string {
  if (!existing.has(base)) return base
  let i = 2
  while (existing.has(`${base}_${i}`)) i += 1
  return `${base}_${i}`
}

function joinChildPath(parent: string, name: string): string {
  return parent === '/' ? `/${name}` : `${parent}/${name}`
}

function DestinationPicker({
  sourceDatasetName,
  value,
  onChange,
  disabled,
}: {
  sourceDatasetName: string
  value: Target | null
  onChange: (t: Target | null) => void
  disabled?: boolean
}) {
  const [currentDir, setCurrentDir] = useState<string | null>(null)
  const [parent, setParent] = useState<string | null>(null)
  const [entries, setEntries] = useState<BrowseDirEntry[]>([])
  const [createOpen, setCreateOpen] = useState(false)
  const [newDatasetName, setNewDatasetName] = useState('')
  const [loading, setLoading] = useState(false)
  const [error, setError] = useState<string | null>(null)
  const [actionError, setActionError] = useState<string | null>(null)
  const browseRequestRef = useRef(0)

  const fetchDir = useCallback(async (path: string | null) => {
    const requestId = browseRequestRef.current + 1
    browseRequestRef.current = requestId
    setLoading(true)
    setError(null)
    setActionError(null)
    try {
      const url = path
        ? `/datasets/browse-dirs?path=${encodeURIComponent(path)}`
        : '/datasets/browse-dirs'
      const resp = await client.get<BrowseDirsResponse>(url)
      if (requestId !== browseRequestRef.current) return
      setCurrentDir(resp.data.path)
      setParent(resp.data.parent)
      setEntries(resp.data.entries)
    } catch (err: unknown) {
      if (requestId !== browseRequestRef.current) return
      const msg = (err as { response?: { data?: { detail?: string } } })?.response?.data?.detail ?? 'Failed to load directory'
      setError(msg)
    } finally {
      if (requestId !== browseRequestRef.current) return
      setLoading(false)
    }
  }, [])

  useEffect(() => { void fetchDir(null) }, [fetchDir])

  const existingNames = new Set(entries.map(entry => entry.name))
  const suggestedName = uniqueName(formatSuggestedName(sourceDatasetName), existingNames)
  const trimmedDatasetName = newDatasetName.trim()
  const hasPathSeparators = /[\\/]/.test(trimmedDatasetName)
  const isReservedDatasetName = trimmedDatasetName === '.' || trimmedDatasetName === '..'
  const invalidDatasetName = trimmedDatasetName.length > 0 && (hasPathSeparators || isReservedDatasetName)
  const hasDuplicateName = trimmedDatasetName.length > 0 && existingNames.has(trimmedDatasetName)
  const resolvedDatasetName = trimmedDatasetName.length > 0
    ? uniqueName(trimmedDatasetName, existingNames)
    : ''
  const canConfirmCreate = Boolean(currentDir) && trimmedDatasetName.length > 0 && !invalidDatasetName && !disabled

  const breadcrumb = currentDir ? currentDir.split('/').filter(Boolean) : []

  const openCreate = () => {
    setCreateOpen(true)
    setNewDatasetName(suggestedName)
    setActionError(null)
  }

  const confirmCreate = () => {
    if (!currentDir) {
      setActionError('Choose a destination directory first')
      return
    }
    if (!trimmedDatasetName) {
      setActionError('Enter a dataset name')
      return
    }
    if (invalidDatasetName) {
      setActionError('Enter a single dataset name, not a path')
      return
    }

    onChange({ mode: 'create', path: joinChildPath(currentDir, resolvedDatasetName) })
    setCreateOpen(false)
    setActionError(null)
  }

  return (
    <div style={s.pickerBox}>
      <div style={s.pickerBreadcrumb}>
        <span style={s.pickerPathRoot}>/</span>
        {breadcrumb.map((seg, i) => (
          <span key={i} style={s.pickerPathSeg}>
            {seg}
            {i < breadcrumb.length - 1 && <span style={s.pickerPathSep}>/</span>}
          </span>
        ))}
      </div>

      <div style={s.pickerList}>
        {loading && <div style={s.pickerHint}>Loading…</div>}
        {!loading && parent && (
          <button
            style={s.pickerEntry}
            onClick={() => void fetchDir(parent)}
            disabled={disabled}
            type="button"
          >
            <span style={s.pickerIcon}>↑</span>
            <span>..</span>
          </button>
        )}
        {!loading && entries.length === 0 && !parent && (
          <div style={s.pickerHint}>No subdirectories</div>
        )}
        {!loading && entries.map(entry => (
          <button
            key={entry.path}
            style={{
              ...s.pickerEntry,
              ...(entry.is_lerobot_dataset && value?.mode === 'merge' && value.path === entry.path ? s.pickerEntrySelected : {}),
            }}
            onClick={() => {
              if (entry.is_lerobot_dataset) {
                onChange({ mode: 'merge', path: entry.path })
                setCreateOpen(false)
                setActionError(null)
                return
              }
              void fetchDir(entry.path)
            }}
            disabled={disabled}
            type="button"
          >
            <span style={s.pickerIcon}>{entry.is_lerobot_dataset ? '◆' : '▸'}</span>
            <span>{entry.name}</span>
          </button>
        ))}
        {error && <div style={s.errorText}>{error}</div>}
      </div>

      <div style={s.pickerCreateRow}>
        {!createOpen ? (
          <button
            style={s.pickerCreateToggleBtn}
            onClick={openCreate}
            disabled={disabled || !currentDir}
            type="button"
          >
            Create new dataset here
          </button>
        ) : (
          <>
            <span style={s.pickerNewLabel}>New dataset name</span>
            <input
              style={s.textInput}
              type="text"
              value={newDatasetName}
              onChange={e => {
                setNewDatasetName(e.target.value)
                setActionError(null)
              }}
              disabled={disabled}
            />
            {trimmedDatasetName.length === 0 ? (
              <div style={s.pickerCreateHint}>Enter a dataset name inside the current directory.</div>
            ) : invalidDatasetName ? (
              <div style={s.errorText}>Use a single dataset name without path separators, `.` or `..`.</div>
            ) : hasDuplicateName ? (
              <div style={s.pickerCreateHint}>
                {joinChildPath(currentDir ?? '/', trimmedDatasetName)} already exists here, so {joinChildPath(currentDir ?? '/', resolvedDatasetName)} will be used instead.
              </div>
            ) : currentDir ? (
              <div style={s.pickerCreateHint}>{joinChildPath(currentDir, trimmedDatasetName)}</div>
            ) : null}
            <div style={s.pickerCreateActions}>
              <button
                style={{ ...s.pickerCreateConfirmBtn, opacity: canConfirmCreate ? 1 : 0.6 }}
                onClick={confirmCreate}
                disabled={!canConfirmCreate}
                type="button"
              >
                Select Create Target
              </button>
              <button
                style={s.refreshBtn}
                onClick={() => {
                  setCreateOpen(false)
                  setActionError(null)
                }}
                disabled={disabled}
                type="button"
              >
                Cancel
              </button>
            </div>
          </>
        )}
      </div>

      {actionError && <div style={s.errorText}>{actionError}</div>}
    </div>
  )
}

function TargetSummary({ target }: { target: Target }) {
  const [summary, setSummary] = useState<SummaryResponse | null>(null)
  const [loading, setLoading] = useState(false)
  const [error, setError] = useState<string | null>(null)

  useEffect(() => {
    if (target.mode === 'create') {
      setSummary(null)
      setLoading(false)
      setError(null)
      return
    }

    let cancelled = false

    const fetchSummary = async () => {
      setLoading(true)
      setError(null)
      setSummary(null)
      try {
        const resp = await client.get<SummaryResponse>(`/datasets/summary?path=${encodeURIComponent(target.path)}`)
        if (!cancelled) {
          setSummary(resp.data)
        }
      } catch (err: unknown) {
        if (cancelled) return
        const msg = (err as { response?: { data?: { detail?: string } } })?.response?.data?.detail ?? 'Failed to load dataset summary'
        setSummary(null)
        setError(msg)
      } finally {
        if (!cancelled) {
          setLoading(false)
        }
      }
    }

    void fetchSummary()

    return () => {
      cancelled = true
    }
  }, [target])

  if (target.mode === 'create') {
    return (
      <div style={s.targetSummaryBox}>
        <div style={s.targetSummaryHead}>Create new Out dataset</div>
        <div style={s.targetSummaryPath}>{target.path}</div>
        <div style={s.targetSummaryCaption}>Selected episodes will be written into a new dataset at this path.</div>
      </div>
    )
  }

  return (
    <div style={s.targetSummaryBox}>
      <div style={s.targetSummaryHead}>Merge into existing dataset</div>
      <div style={s.targetSummaryPath}>{target.path}</div>
      {loading && <div style={s.targetSummaryCaption}>Loading dataset summary...</div>}
      {error && <div style={s.errorText}>{error}</div>}
      {!loading && !error && summary && (
        <>
          <div style={s.targetSummaryMetrics}>
            <div style={s.targetMetric}>
              <span style={s.targetMetricLabel}>Episodes</span>
              <span style={s.targetMetricValue}>{summary.total_episodes}</span>
            </div>
            <div style={s.targetMetric}>
              <span style={s.targetMetricLabel}>Robot</span>
              <span style={s.targetMetricValue}>{summary.robot_type ?? 'Unknown'}</span>
            </div>
            <div style={s.targetMetric}>
              <span style={s.targetMetricLabel}>FPS</span>
              <span style={s.targetMetricValue}>{summary.fps}</span>
            </div>
            <div style={s.targetMetric}>
              <span style={s.targetMetricLabel}>Features</span>
              <span style={s.targetMetricValue}>{summary.features_count}</span>
            </div>
          </div>
          <div style={s.targetSummaryCaption}>Existing dataset metadata loaded from `meta/info.json`.</div>
        </>
      )}
    </div>
  )
}

function OutTab({
  datasetPath,
  episodes,
}: {
  datasetPath: string | null
  episodes: Episode[]
}) {
  const [selectedGrades, setSelectedGrades] = useState<Set<string>>(new Set())
  const [selectedTags, setSelectedTags] = useState<Set<string>>(new Set())
  const [target, setTarget] = useState<Target | null>(null)
  const [submitting, setSubmitting] = useState(false)
  const [submitError, setSubmitError] = useState<string | null>(null)
  const { jobStatus, polling, startPolling, reset } = useJobPoller()

  useEffect(() => {
    setSelectedGrades(new Set())
    setSelectedTags(new Set())
    setTarget(null)
    setSubmitting(false)
    setSubmitError(null)
    reset()
  }, [datasetPath, reset])

  const allTags = Array.from(new Set(episodes.flatMap(e => e.tags ?? []))).sort()
  const matchingEpisodes = episodes
    .filter(e => selectedGrades.size === 0 || selectedGrades.has(e.grade ?? 'Ungraded'))
    .filter(e => selectedTags.size === 0 || (e.tags ?? []).some(t => selectedTags.has(t)))

  const toggleGrade = (grade: string) => {
    setSelectedGrades(prev => {
      const next = new Set(prev)
      if (next.has(grade)) next.delete(grade)
      else next.add(grade)
      return next
    })
  }

  const toggleTag = (tag: string) => {
    setSelectedTags(prev => {
      const next = new Set(prev)
      if (next.has(tag)) next.delete(tag)
      else next.add(tag)
      return next
    })
  }

  const handleSubmit = async () => {
    if (!datasetPath) return
    if (matchingEpisodes.length === 0) {
      setSubmitError('No episodes match the selected grade and tag filters')
      return
    }
    if (!target) {
      setSubmitError('Choose where the Out dataset should be created or merged')
      return
    }

    setSubmitting(true)
    setSubmitError(null)
    reset()

    try {
      const resp = await client.post<{ job_id: string; operation: string; status: string }>('/datasets/split-into', {
        source_path: datasetPath,
        episode_ids: matchingEpisodes.map(e => e.episode_index).sort((a, b) => a - b),
        destination_path: target.path,
      })
      startPolling(resp.data.job_id)
    } catch (err: unknown) {
      const msg = (err as { response?: { data?: { detail?: string } } })?.response?.data?.detail ?? 'Out run failed'
      setSubmitError(msg)
    } finally {
      setSubmitting(false)
    }
  }

  if (!datasetPath) {
    return <div style={s.emptyState}>Load a dataset first to prepare an Out dataset.</div>
  }

  const datasetSegments = datasetPath.split('/').filter(Boolean)
  const sourceDatasetName = datasetSegments[datasetSegments.length - 1] ?? 'dataset'
  const syncComplete = jobStatus?.status === 'complete' || jobStatus?.status === 'completed'
  const submitDisabled = submitting || polling || !target || matchingEpisodes.length === 0

  return (
    <div style={s.tabContent}>
      <div style={s.fieldLabel}>Filter by Grade</div>
      <div style={s.chipRow}>
        {GRADE_OPTIONS.map(grade => {
          const active = selectedGrades.has(grade)
          const color = grade === 'good' ? 'var(--c-green)' : grade === 'bad' ? 'var(--c-red)' : grade === 'normal' ? 'var(--c-yellow)' : 'var(--text-muted)'
          return (
            <button
              key={grade}
              style={{
                ...s.chip,
                borderColor: active ? color : 'var(--border3)',
                color: active ? color : 'var(--text-dim)',
                background: active ? `${color}18` : 'transparent',
              }}
              onClick={() => toggleGrade(grade)}
              type="button"
            >
              {grade}
            </button>
          )
        })}
      </div>

      <div style={s.fieldLabel}>Filter by Tag</div>
      {allTags.length === 0 ? (
        <div style={s.empty}>No tags found in this dataset.</div>
      ) : (
        <div style={s.chipRow}>
          {allTags.map(tag => {
            const active = selectedTags.has(tag)
            return (
              <button
                key={tag}
                style={{
                  ...s.chip,
                  borderColor: active ? 'var(--interactive)' : 'var(--border3)',
                  color: active ? 'var(--interactive)' : 'var(--text-dim)',
                  background: active ? 'var(--interactive-dim)' : 'transparent',
                }}
                onClick={() => toggleTag(tag)}
                type="button"
              >
                {tag}
              </button>
            )
          })}
        </div>
      )}

      <div style={s.matchPreview}>
        <span style={{ color: matchingEpisodes.length > 0 ? 'var(--interactive)' : 'var(--c-red)' }}>
          {matchingEpisodes.length} episode{matchingEpisodes.length !== 1 ? 's' : ''} selected for Out
        </span>
        {matchingEpisodes.length > 0 ? (
          <>
            <div style={s.matchRanges}>
              {formatEpisodeRanges(matchingEpisodes.map(e => e.episode_index))}
            </div>
            <span style={s.targetSummaryCaption}>
              {selectedGrades.size === 0 && selectedTags.size === 0
                ? 'No filters selected, so all episodes will be included.'
                : 'Episodes must match every active grade and tag filter.'}
            </span>
          </>
        ) : (
          <span style={s.errorText}>
            No episodes match the current filters. Clear one or more filters to enable Run Out.
          </span>
        )}
      </div>

      <div style={s.fieldLabel}>Destination</div>
      <DestinationPicker
        sourceDatasetName={sourceDatasetName}
        value={target}
        onChange={setTarget}
        disabled={submitting || polling}
      />
      {target && <TargetSummary target={target} />}

      {submitError && <div style={s.errorText}>{submitError}</div>}

      {syncComplete && jobStatus?.summary && (
        <div style={s.matchPreview}>
          <span style={{ color: 'var(--c-green)' }}>
            {jobStatus.summary.created} copied, {jobStatus.summary.skipped_duplicates} skipped as duplicates
          </span>
          <span style={{ color: 'var(--text-muted)' }}>
            Mode: {jobStatus.summary.mode}
          </span>
        </div>
      )}

      <button
        style={{ ...s.actionBtn, opacity: submitDisabled ? 0.6 : 1 }}
        onClick={handleSubmit}
        disabled={submitDisabled}
      >
        {submitting ? 'Submitting...' : 'Run Out'}
      </button>

      <JobProgress jobStatus={jobStatus} polling={polling} />
    </div>
  )
}

function DeleteTab({
  datasetPath,
  episodes,
}: {
  datasetPath: string | null
  episodes: Episode[]
}) {
  const [splitMode, setSplitMode] = useState<SplitMode>('grade')
  const [selectedGrades, setSelectedGrades] = useState<Set<string>>(new Set())
  const [selectedTags, setSelectedTags] = useState<Set<string>>(new Set())
  const [submitting, setSubmitting] = useState(false)
  const [submitError, setSubmitError] = useState<string | null>(null)
  const { jobStatus, polling, startPolling, reset } = useJobPoller()

  const allTags = Array.from(new Set(episodes.flatMap(e => e.tags ?? []))).sort()

  const matchingEpisodes = splitMode === 'grade'
    ? episodes.filter(e => selectedGrades.has(e.grade ?? 'Ungraded'))
    : episodes.filter(e => (e.tags ?? []).some(t => selectedTags.has(t)))

  const toggleGrade = (grade: string) => {
    setSelectedGrades(prev => {
      const next = new Set(prev)
      if (next.has(grade)) next.delete(grade)
      else next.add(grade)
      return next
    })
  }

  const toggleTag = (tag: string) => {
    setSelectedTags(prev => {
      const next = new Set(prev)
      if (next.has(tag)) next.delete(tag)
      else next.add(tag)
      return next
    })
  }

  const handleSubmit = async () => {
    if (!datasetPath) return
    if (matchingEpisodes.length === 0) { setSubmitError('No episodes match the selected filter'); return }
    if (matchingEpisodes.length === episodes.length) { setSubmitError('Cannot delete all episodes'); return }

    setSubmitting(true)
    setSubmitError(null)
    reset()

    try {
      const episodeIds = matchingEpisodes.map(e => e.episode_index).sort((a, b) => a - b)
      const resp = await client.post<{ job_id: string; operation: string; status: string }>('/datasets/delete', {
        source_path: datasetPath,
        episode_ids: episodeIds,
      })
      startPolling(resp.data.job_id)
    } catch (err: unknown) {
      const msg = (err as { response?: { data?: { detail?: string } } })?.response?.data?.detail ?? 'Delete failed'
      setSubmitError(msg)
    } finally {
      setSubmitting(false)
    }
  }

  if (!datasetPath) {
    return <div style={s.emptyState}>Load a dataset first to delete episodes.</div>
  }

  return (
    <div style={s.tabContent}>
      <div style={s.fieldLabel}>Delete By</div>
      <div style={s.modeToggle}>
        {(['grade', 'tag'] as SplitMode[]).map(mode => (
          <button
            key={mode}
            style={{ ...s.modeBtn, ...(splitMode === mode ? s.modeBtnActive : {}) }}
            onClick={() => setSplitMode(mode)}
          >
            {mode === 'grade' ? 'Grade' : 'Tag'}
          </button>
        ))}
      </div>

      {splitMode === 'grade' && (
        <>
          <div style={s.fieldLabel}>Select grades to delete</div>
          <div style={s.chipRow}>
            {GRADE_OPTIONS.map(grade => {
              const active = selectedGrades.has(grade)
              const color = grade === 'good' ? 'var(--c-green)' : grade === 'bad' ? 'var(--c-red)' : grade === 'normal' ? 'var(--c-yellow)' : 'var(--text-muted)'
              return (
                <button
                  key={grade}
                  style={{
                    ...s.chip,
                    borderColor: active ? color : '#333',
                    color: active ? color : '#666',
                    background: active ? `${color}18` : 'transparent',
                  }}
                  onClick={() => toggleGrade(grade)}
                >
                  {grade}
                </button>
              )
            })}
          </div>
        </>
      )}

      {splitMode === 'tag' && (
        <>
          <div style={s.fieldLabel}>Select tags to delete</div>
          {allTags.length === 0 ? (
            <div style={s.empty}>No tags found in this dataset.</div>
          ) : (
            <div style={s.chipRow}>
              {allTags.map(tag => {
                const active = selectedTags.has(tag)
                return (
                  <button
                    key={tag}
                    style={{
                      ...s.chip,
                      borderColor: active ? 'var(--c-red)' : 'var(--border3)',
                      color: active ? 'var(--c-red)' : 'var(--text-dim)',
                      background: active ? 'var(--c-red-dim)' : 'transparent',
                    }}
                    onClick={() => toggleTag(tag)}
                  >
                    {tag}
                  </button>
                )
              })}
            </div>
          )}
        </>
      )}

      <div style={s.matchPreview}>
        <span style={{ color: matchingEpisodes.length > 0 ? 'var(--c-red)' : 'var(--text-dim)' }}>
          {matchingEpisodes.length} episode{matchingEpisodes.length !== 1 ? 's' : ''} will be deleted
        </span>
        {matchingEpisodes.length > 0 && (
          <div style={s.matchRanges}>
            {formatEpisodeRanges(matchingEpisodes.map(e => e.episode_index))}
          </div>
        )}
        {matchingEpisodes.length > 0 && (
          <span style={{ fontSize: 11, color: 'var(--text-muted)' }}>
            {episodes.length - matchingEpisodes.length} episode{episodes.length - matchingEpisodes.length !== 1 ? 's' : ''} will remain
          </span>
        )}
      </div>

      {submitError && <div style={s.errorText}>{submitError}</div>}

      <button
        style={{ ...s.actionBtn, background: 'var(--c-red)', opacity: submitting || polling ? 0.6 : 1 }}
        onClick={handleSubmit}
        disabled={submitting || polling}
      >
        {submitting ? 'Submitting...' : 'Delete Episodes'}
      </button>

      <JobProgress jobStatus={jobStatus} polling={polling} />
    </div>
  )
}

function CyclesTab({ datasetPath }: { datasetPath: string | null }) {
  const [status, setStatus] = useState<StampStatus | null>(null)
  const [statusLoading, setStatusLoading] = useState(false)
  const [statusError, setStatusError] = useState<string | null>(null)
  const [confirmOpen, setConfirmOpen] = useState(false)
  const [submitting, setSubmitting] = useState(false)
  const [submitError, setSubmitError] = useState<string | null>(null)
  const { jobStatus, polling, startPolling, reset } = useJobPoller()
  const datasetPathRef = useRef<string | null>(datasetPath)
  const asyncScopeRef = useRef(0)

  const refreshStatus = useCallback(async () => {
    if (!datasetPath) {
      setStatus(null)
      setStatusLoading(false)
      setStatusError(null)
      return
    }

    const scopeId = asyncScopeRef.current
    const requestPath = datasetPath
    setStatusLoading(true)
    setStatusError(null)

    try {
      const resp = await client.get<StampStatus>('/datasets/stamp-cycles/status', {
        params: { path: datasetPath },
      })
      if (scopeId !== asyncScopeRef.current || datasetPathRef.current !== requestPath) return
      setStatus(resp.data)
    } catch (err: unknown) {
      if (scopeId !== asyncScopeRef.current || datasetPathRef.current !== requestPath) return
      const msg = (err as { response?: { data?: { detail?: string } } })?.response?.data?.detail ?? 'Failed to read stamp status'
      setStatusError(msg)
      setStatus(null)
    } finally {
      if (scopeId !== asyncScopeRef.current || datasetPathRef.current !== requestPath) return
      setStatusLoading(false)
    }
  }, [datasetPath])

  useEffect(() => {
    datasetPathRef.current = datasetPath
    asyncScopeRef.current += 1
    setStatus(null)
    setStatusLoading(false)
    setStatusError(null)
    setConfirmOpen(false)
    setSubmitting(false)
    setSubmitError(null)
    reset()
    if (datasetPath) {
      void refreshStatus()
    }
  }, [datasetPath, refreshStatus, reset])

  useEffect(() => {
    const nextStatus = jobStatus?.status
    if (nextStatus === 'complete' || nextStatus === 'completed') {
      setConfirmOpen(false)
      void refreshStatus()
    }
  }, [jobStatus?.status, refreshStatus])

  const submit = useCallback(async (overwrite: boolean) => {
    if (!datasetPath) return

    const scopeId = asyncScopeRef.current
    const requestPath = datasetPath
    setSubmitting(true)
    setSubmitError(null)
    reset()

    try {
      const resp = await client.post<{ job_id: string; operation: string; status: string }>(
        '/datasets/stamp-cycles',
        { source_path: datasetPath, overwrite },
      )
      if (scopeId !== asyncScopeRef.current || datasetPathRef.current !== requestPath) return
      startPolling(resp.data.job_id)
    } catch (err: unknown) {
      if (scopeId !== asyncScopeRef.current || datasetPathRef.current !== requestPath) return
      const msg = (err as { response?: { data?: { detail?: string } } })?.response?.data?.detail ?? 'Stamp failed'
      setSubmitError(msg)
    } finally {
      if (scopeId !== asyncScopeRef.current || datasetPathRef.current !== requestPath) return
      setSubmitting(false)
    }
  }, [datasetPath, reset, startPolling])

  const handlePrimaryClick = () => {
    if (!status || statusLoading || statusError) return

    if (status?.stamped) {
      setConfirmOpen(true)
      return
    }

    void submit(false)
  }

  const canSubmit = Boolean(status) && !statusLoading && !statusError && !submitting && !polling

  if (!datasetPath) {
    return <div style={s.emptyState}>Load a dataset first to stamp cycle markers.</div>
  }

  return (
    <div style={s.tabContent}>
      <div style={s.matchPreview}>
        {statusLoading && <span style={{ color: 'var(--text-dim)' }}>Checking current stamp status...</span>}
        {statusError && <span style={s.errorText}>{statusError}</span>}
        {!statusLoading && !statusError && status && (
          status.stamped ? (
            <span style={{ color: 'var(--c-yellow)' }}>
              Already stamped. Sampled first parquet shows {status.is_terminal_count_sample} `is_terminal` flags. Overwriting will rewrite the parquet files in place.
            </span>
          ) : (
            <span style={{ color: 'var(--text-muted)' }}>
              No cycle markers detected yet. Stamping rewrites the dataset parquet files in place.
            </span>
          )
        )}
        {!statusLoading && !statusError && !status && (
          <span style={{ color: 'var(--text-dim)' }}>
            Stamp status is not available yet. Retry the status check before running this action.
          </span>
        )}
      </div>

      {submitError && <div style={s.errorText}>{submitError}</div>}

      <div style={{ display: 'flex', gap: 8, alignItems: 'center', flexWrap: 'wrap' }}>
        <button
          style={{ ...s.actionBtn, opacity: canSubmit ? 1 : 0.6 }}
          onClick={handlePrimaryClick}
          disabled={!canSubmit}
        >
          {submitting ? 'Submitting...' : status?.stamped ? 'Overwrite Cycle Markers' : 'Stamp Cycles'}
        </button>

        {(statusError || !status) && !statusLoading && (
          <button
            style={{ ...s.refreshBtn, padding: '6px 12px' }}
            onClick={() => { void refreshStatus() }}
            disabled={submitting || polling}
          >
            Retry Status Check
          </button>
        )}
      </div>

      <JobProgress jobStatus={jobStatus} polling={polling} />

      {confirmOpen && (
        <div style={s.matchPreview}>
          <span style={{ color: 'var(--c-yellow)' }}>
            This dataset already has cycle markers. Overwrite will replace the existing `is_terminal` and `is_last` columns in place.
          </span>
          <div style={{ display: 'flex', gap: 6, marginTop: 6 }}>
            <button
              style={{ ...s.actionBtn, background: 'var(--c-red)' }}
              onClick={() => {
                setConfirmOpen(false)
                void submit(true)
              }}
              disabled={submitting || polling}
            >
              Overwrite In Place
            </button>
            <button
              style={{ ...s.refreshBtn, padding: '6px 12px' }}
              onClick={() => setConfirmOpen(false)}
              disabled={submitting || polling}
            >
              Cancel
            </button>
          </div>
        </div>
      )}
    </div>
  )
}

export function TrimPanel({ datasetPath, episodes }: TrimPanelProps) {
  const [tab, setTab] = useState<TabId>('out')

  return (
    <div style={s.container}>
      <div style={s.body}>
        <div style={s.tabs}>
          {(['out', 'delete', 'cycles'] as TabId[]).map(t => (
            <button
              key={t}
              style={{ ...s.tabBtn, ...(tab === t ? (t === 'delete' ? { ...s.tabBtnActive, color: 'var(--c-red)' } : s.tabBtnActive) : {}) }}
              onClick={() => setTab(t)}
            >
              {t.charAt(0).toUpperCase() + t.slice(1)}
            </button>
          ))}
        </div>

        {tab === 'out' && <OutTab datasetPath={datasetPath} episodes={episodes} />}
        {tab === 'delete' && <DeleteTab datasetPath={datasetPath} episodes={episodes} />}
        {tab === 'cycles' && <CyclesTab datasetPath={datasetPath} />}
      </div>
    </div>
  )
}

const s: Record<string, React.CSSProperties> = {
  container: {
    borderBottom: '1px solid var(--border3)',
  },
  body: {
    padding: '0 12px 12px',
    display: 'flex',
    flexDirection: 'column' as const,
    gap: 8,
  },
  tabs: {
    display: 'flex',
    gap: 4,
    borderBottom: '1px solid var(--border2)',
    paddingBottom: 6,
  },
  tabBtn: {
    background: 'transparent',
    border: 'none',
    color: 'var(--text-dim)',
    fontSize: 12,
    padding: '4px 10px',
    cursor: 'pointer',
    borderRadius: '3px 3px 0 0',
  },
  tabBtnActive: {
    color: 'var(--interactive)',
    background: 'var(--border2)',
  },
  tabContent: {
    display: 'flex',
    flexDirection: 'column' as const,
    gap: 8,
  },
  fieldLabel: {
    fontSize: 11,
    color: 'var(--text-muted)',
    textTransform: 'uppercase' as const,
    letterSpacing: '0.05em',
    display: 'flex',
    alignItems: 'center',
    gap: 8,
  },
  modeToggle: {
    display: 'flex',
    gap: 4,
  },
  modeBtn: {
    background: 'transparent',
    border: '1px solid var(--border3)',
    borderRadius: 4,
    color: 'var(--text-dim)',
    fontSize: 12,
    padding: '4px 12px',
    cursor: 'pointer',
  },
  modeBtnActive: {
    background: '#2a3a4a',
    border: '1px solid var(--interactive)',
    color: 'var(--interactive)',
  },
  chipRow: {
    display: 'flex',
    flexWrap: 'wrap' as const,
    gap: 6,
  },
  chip: {
    background: 'transparent',
    border: '1px solid var(--border3)',
    borderRadius: 12,
    fontSize: 11,
    fontWeight: 600,
    padding: '3px 10px',
    cursor: 'pointer',
    transition: 'all 0.1s',
  },
  matchPreview: {
    background: 'var(--panel2)',
    border: '1px solid var(--border2)',
    borderRadius: 4,
    padding: '8px 10px',
    fontSize: 12,
    display: 'flex',
    flexDirection: 'column' as const,
    gap: 4,
  },
  matchRanges: {
    fontSize: 11,
    color: 'var(--text-muted)',
    fontFamily: 'var(--font-mono)',
    wordBreak: 'break-all' as const,
  },
  refreshBtn: {
    background: 'transparent',
    border: '1px solid var(--border3)',
    borderRadius: 3,
    color: 'var(--text-muted)',
    fontSize: 10,
    padding: '2px 6px',
    cursor: 'pointer',
  },
  textInput: {
    background: 'var(--border2)',
    border: '1px solid var(--border3)',
    borderRadius: 4,
    color: 'var(--text)',
    padding: '6px 8px',
    fontSize: 12,
    outline: 'none',
    width: '100%',
    boxSizing: 'border-box' as const,
  },
  actionBtn: {
    background: 'var(--interactive)',
    border: 'none',
    borderRadius: 4,
    color: '#fff',
    padding: '7px 14px',
    fontSize: 12,
    cursor: 'pointer',
    alignSelf: 'flex-start' as const,
  },
  statusBox: {
    background: 'var(--panel2)',
    border: '1px solid var(--border3)',
    borderRadius: 4,
    padding: '8px 10px',
    display: 'flex',
    flexDirection: 'column' as const,
    gap: 4,
    fontSize: 12,
  },
  resultPath: {
    fontSize: 11,
    color: 'var(--text-muted)',
    wordBreak: 'break-all' as const,
  },
  errorText: {
    fontSize: 12,
    color: 'var(--c-red)',
  },
  spinner: {
    display: 'inline-block',
    animation: 'spin 1s linear infinite',
    fontSize: 14,
  },
  empty: {
    color: 'var(--text-dim)',
    fontSize: 12,
    padding: '6px 0',
  },
  pickerBox: {
    display: 'flex',
    flexDirection: 'column' as const,
    gap: 6,
    background: 'var(--panel2)',
    border: '1px solid var(--border2)',
    borderRadius: 4,
    padding: 8,
  },
  pickerBreadcrumb: {
    display: 'flex',
    flexWrap: 'wrap' as const,
    alignItems: 'center',
    gap: 2,
    fontSize: 11,
    color: 'var(--text-muted)',
    fontFamily: 'var(--font-mono)',
    padding: '2px 4px',
  },
  pickerPathRoot: {
    color: 'var(--text-dim)',
  },
  pickerPathSeg: {
    color: 'var(--text)',
    display: 'inline-flex',
    alignItems: 'center',
  },
  pickerPathSep: {
    color: 'var(--text-dim)',
    margin: '0 2px',
  },
  pickerList: {
    display: 'flex',
    flexDirection: 'column' as const,
    gap: 2,
    maxHeight: 200,
    overflowY: 'auto' as const,
    border: '1px solid var(--border3)',
    borderRadius: 3,
    padding: 4,
    background: 'var(--panel)',
  },
  pickerEntry: {
    display: 'flex',
    alignItems: 'center',
    gap: 8,
    background: 'transparent',
    border: 'none',
    color: 'var(--text)',
    textAlign: 'left' as const,
    fontSize: 12,
    padding: '4px 8px',
    borderRadius: 3,
    cursor: 'pointer',
  },
  pickerEntrySelected: {
    background: 'var(--interactive-dim)',
    color: 'var(--interactive)',
    border: '1px solid var(--interactive)',
  },
  pickerIcon: {
    color: 'var(--text-dim)',
    fontSize: 11,
    width: 12,
    display: 'inline-block',
  },
  pickerHint: {
    color: 'var(--text-dim)',
    fontSize: 11,
    padding: '4px 8px',
  },
  pickerCreateRow: {
    display: 'flex',
    flexDirection: 'column' as const,
    gap: 4,
  },
  pickerCreateActions: {
    display: 'flex',
    gap: 6,
    flexWrap: 'wrap' as const,
  },
  pickerCreateToggleBtn: {
    background: 'transparent',
    border: '1px dashed var(--border3)',
    borderRadius: 4,
    color: 'var(--text)',
    fontSize: 12,
    padding: '6px 10px',
    cursor: 'pointer',
    alignSelf: 'flex-start' as const,
  },
  pickerCreateConfirmBtn: {
    background: 'var(--interactive)',
    border: 'none',
    borderRadius: 4,
    color: '#fff',
    fontSize: 12,
    padding: '6px 10px',
    cursor: 'pointer',
  },
  pickerCreateHint: {
    color: 'var(--text-muted)',
    fontSize: 11,
    fontFamily: 'var(--font-mono)',
    wordBreak: 'break-all' as const,
  },
  pickerNewLabel: {
    fontSize: 10,
    color: 'var(--text-muted)',
    textTransform: 'uppercase' as const,
    letterSpacing: '0.05em',
  },
  targetSummaryBox: {
    display: 'flex',
    flexDirection: 'column' as const,
    gap: 8,
    background: 'var(--panel2)',
    border: '1px solid var(--border2)',
    borderRadius: 4,
    padding: '8px 10px',
  },
  targetSummaryHead: {
    fontSize: 11,
    fontWeight: 700,
    color: 'var(--text)',
    textTransform: 'uppercase' as const,
    letterSpacing: '0.05em',
  },
  targetSummaryPath: {
    color: 'var(--text)',
    fontFamily: 'var(--font-mono)',
    fontSize: 11,
    wordBreak: 'break-all' as const,
  },
  targetSummaryCaption: {
    color: 'var(--text-muted)',
    fontSize: 11,
  },
  targetSummaryMetrics: {
    display: 'grid',
    gridTemplateColumns: 'repeat(auto-fit, minmax(90px, 1fr))',
    gap: 6,
  },
  targetMetric: {
    display: 'flex',
    flexDirection: 'column' as const,
    gap: 2,
    padding: '6px 8px',
    background: 'var(--panel)',
    border: '1px solid var(--border3)',
    borderRadius: 4,
  },
  targetMetricLabel: {
    color: 'var(--text-muted)',
    fontSize: 10,
    textTransform: 'uppercase' as const,
    letterSpacing: '0.05em',
  },
  targetMetricValue: {
    color: 'var(--text)',
    fontSize: 12,
    fontWeight: 600,
  },
  emptyState: {
    fontSize: 13,
    color: 'var(--color-text-dim)',
    padding: '24px',
    textAlign: 'center' as const,
  },
}
