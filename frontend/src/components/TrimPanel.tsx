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

type TabId = 'split' | 'merge' | 'delete' | 'cycles'

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

function SplitTab({
  datasetPath,
  episodes,
}: {
  datasetPath: string | null
  episodes: Episode[]
}) {
  const [selectedTags, setSelectedTags] = useState<Set<string>>(new Set())
  const [destinationPath, setDestinationPath] = useState('')
  const [submitting, setSubmitting] = useState(false)
  const [submitError, setSubmitError] = useState<string | null>(null)
  const { jobStatus, polling, startPolling, reset } = useJobPoller()

  const goodEpisodes = episodes.filter(e => e.grade === 'good')
  const allTags = Array.from(
    new Set(goodEpisodes.flatMap(e => e.tags ?? [])),
  ).sort()
  const matchingEpisodes = selectedTags.size === 0
    ? goodEpisodes
    : goodEpisodes.filter(e => (e.tags ?? []).some(tag => selectedTags.has(tag)))

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
      setSubmitError('No good episodes match the selected tags')
      return
    }
    if (!destinationPath.trim()) {
      setSubmitError('Enter an absolute destination path')
      return
    }

    setSubmitting(true)
    setSubmitError(null)
    reset()

    try {
      const resp = await client.post<{ job_id: string; operation: string; status: string }>('/datasets/split-into', {
        source_path: datasetPath,
        episode_ids: matchingEpisodes.map(e => e.episode_index).sort((a, b) => a - b),
        destination_path: destinationPath.trim(),
      })
      startPolling(resp.data.job_id)
    } catch (err: unknown) {
      const msg = (err as { response?: { data?: { detail?: string } } })?.response?.data?.detail ?? 'Sync failed'
      setSubmitError(msg)
    } finally {
      setSubmitting(false)
    }
  }

  if (!datasetPath) {
    return <div style={s.emptyState}>Load a dataset first to sync good episodes.</div>
  }

  const syncComplete = jobStatus?.status === 'complete' || jobStatus?.status === 'completed'
  const submitDisabled = submitting || polling || !destinationPath.trim() || matchingEpisodes.length === 0

  return (
    <div style={s.tabContent}>
      <div style={s.fieldLabel}>Good Episode Filter</div>
      {allTags.length === 0 ? (
        <div style={s.empty}>No tags found on good episodes. All good episodes will be synced.</div>
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
              >
                {tag}
              </button>
            )
          })}
        </div>
      )}

      <div style={s.matchPreview}>
        <span style={{ color: matchingEpisodes.length > 0 ? 'var(--interactive)' : 'var(--text-dim)' }}>
          {matchingEpisodes.length} good episode{matchingEpisodes.length !== 1 ? 's' : ''} selected
        </span>
        {matchingEpisodes.length > 0 && (
          <div style={s.matchRanges}>
            {formatEpisodeRanges(matchingEpisodes.map(e => e.episode_index))}
          </div>
        )}
      </div>

      <div style={s.fieldLabel}>Destination Path</div>
      <input
        style={s.textInput}
        type="text"
        placeholder="/absolute/path/to/good-sync"
        value={destinationPath}
        onChange={e => setDestinationPath(e.target.value)}
        disabled={submitting || polling}
      />

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
        {submitting ? 'Submitting...' : 'Sync Good Episodes'}
      </button>

      <JobProgress jobStatus={jobStatus} polling={polling} />
    </div>
  )
}

function MergeTab() {
  const [availableDatasets, setAvailableDatasets] = useState<{ name: string; path: string }[]>([])
  const [loadingDatasets, setLoadingDatasets] = useState(false)
  const [datasetsError, setDatasetsError] = useState<string | null>(null)
  const [selectedPaths, setSelectedPaths] = useState<Set<string>>(new Set())
  const [targetName, setTargetName] = useState('')
  const [submitting, setSubmitting] = useState(false)
  const [submitError, setSubmitError] = useState<string | null>(null)
  const { jobStatus, polling, startPolling, reset } = useJobPoller()

  const fetchDatasets = useCallback(async () => {
    setLoadingDatasets(true)
    setDatasetsError(null)
    try {
      // Fetch available datasets list
      const resp = await client.get<{ name: string; path: string }[]>('/datasets/list')
      setAvailableDatasets(resp.data)
    } catch {
      setDatasetsError('Failed to load datasets')
    } finally {
      setLoadingDatasets(false)
    }
  }, [])

  useEffect(() => {
    void fetchDatasets()
  }, [fetchDatasets])

  const toggleDataset = (path: string) => {
    setSelectedPaths(prev => {
      const next = new Set(prev)
      if (next.has(path)) next.delete(path)
      else next.add(path)
      return next
    })
  }

  const handleSubmit = async () => {
    if (selectedPaths.size < 2) { setSubmitError('Select at least 2 datasets'); return }
    if (!targetName.trim()) { setSubmitError('Enter a target dataset name'); return }

    setSubmitting(true)
    setSubmitError(null)
    reset()

    try {
      const resp = await client.post<{ job_id: string; operation: string; status: string }>('/datasets/merge', {
        source_paths: Array.from(selectedPaths),
        target_name: targetName.trim(),
      })
      startPolling(resp.data.job_id)
    } catch (err: unknown) {
      const msg = (err as { response?: { data?: { detail?: string } } })?.response?.data?.detail ?? 'Merge failed'
      setSubmitError(msg)
    } finally {
      setSubmitting(false)
    }
  }

  return (
    <div style={s.tabContent}>
      <div style={{ display: 'flex', alignItems: 'center', justifyContent: 'space-between', marginBottom: 4 }}>
        <div style={s.fieldLabel}>
          Datasets ({selectedPaths.size} selected)
        </div>
        <button style={s.refreshBtn} onClick={fetchDatasets} disabled={loadingDatasets}>
          {loadingDatasets ? '...' : 'Refresh'}
        </button>
      </div>

      {datasetsError && <div style={s.errorText}>{datasetsError}</div>}

      <div style={s.episodeList}>
        {loadingDatasets && <div style={s.empty}>Loading...</div>}
        {!loadingDatasets && availableDatasets.length === 0 && (
          <div style={s.emptyState}>No datasets available for merge. Mount datasets via Hub Sync first.</div>
        )}
        {availableDatasets.map(ds => (
          <label key={ds.path} style={s.checkRow}>
            <input
              type="checkbox"
              checked={selectedPaths.has(ds.path)}
              onChange={() => toggleDataset(ds.path)}
              style={s.checkbox}
            />
            <span style={s.epLabel}>
              <span style={{ ...s.epIndex, color: 'var(--interactive)' }}>{ds.name}</span>
              <span style={s.epTask}>{ds.path}</span>
            </span>
          </label>
        ))}
      </div>

      <div style={s.fieldLabel}>Target dataset name</div>
      <input
        style={s.textInput}
        type="text"
        placeholder="e.g. merged_dataset"
        value={targetName}
        onChange={e => setTargetName(e.target.value)}
        disabled={submitting || polling}
      />

      {submitError && <div style={s.errorText}>{submitError}</div>}

      <button
        style={{ ...s.actionBtn, opacity: submitting || polling ? 0.6 : 1 }}
        onClick={handleSubmit}
        disabled={submitting || polling}
      >
        {submitting ? 'Submitting...' : 'Merge Datasets'}
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
  const [tab, setTab] = useState<TabId>('split')

  return (
    <div style={s.container}>
      <div style={s.body}>
        <div style={s.tabs}>
          {(['split', 'merge', 'delete', 'cycles'] as TabId[]).map(t => (
            <button
              key={t}
              style={{ ...s.tabBtn, ...(tab === t ? (t === 'delete' ? { ...s.tabBtnActive, color: 'var(--c-red)' } : s.tabBtnActive) : {}) }}
              onClick={() => setTab(t)}
            >
              {t.charAt(0).toUpperCase() + t.slice(1)}
            </button>
          ))}
        </div>

        {tab === 'split' && <SplitTab datasetPath={datasetPath} episodes={episodes} />}
        {tab === 'merge' && <MergeTab />}
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
  selectAllBtn: {
    background: 'transparent',
    border: '1px solid var(--border3)',
    borderRadius: 3,
    color: 'var(--text-muted)',
    fontSize: 10,
    padding: '2px 6px',
    cursor: 'pointer',
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
  episodeList: {
    maxHeight: 180,
    overflowY: 'auto' as const,
    display: 'flex',
    flexDirection: 'column' as const,
    gap: 2,
    background: 'var(--panel2)',
    borderRadius: 4,
    border: '1px solid var(--border2)',
    padding: '4px',
  },
  checkRow: {
    display: 'flex',
    alignItems: 'center',
    gap: 8,
    padding: '4px 6px',
    borderRadius: 3,
    cursor: 'pointer',
    fontSize: 12,
  },
  checkbox: {
    flexShrink: 0,
    accentColor: 'var(--interactive)',
  },
  epLabel: {
    display: 'flex',
    alignItems: 'center',
    gap: 6,
    minWidth: 0,
    overflow: 'hidden',
  },
  epIndex: {
    color: '#888',
    fontSize: 11,
    fontFamily: 'var(--font-mono)',
    flexShrink: 0,
  },
  gradeTag: {
    fontSize: 10,
    fontWeight: 600,
    flexShrink: 0,
  },
  epTask: {
    color: 'var(--text-muted)',
    fontSize: 11,
    overflow: 'hidden',
    textOverflow: 'ellipsis',
    whiteSpace: 'nowrap' as const,
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
  emptyState: {
    fontSize: 13,
    color: 'var(--color-text-dim)',
    padding: '24px',
    textAlign: 'center' as const,
  },
}
