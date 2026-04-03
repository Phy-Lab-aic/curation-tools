import { useState, useEffect, useCallback } from 'react'
import client from '../api/client'
import type { Episode } from '../types/index'

interface SplitMergePanelProps {
  datasetPath: string | null
  episodes: Episode[]
}

interface JobStatus {
  job_id: string
  operation: string
  status: string
  created_at: string
  completed_at: string | null
  error: string | null
  result_path: string | null
}

interface DerivedDataset {
  name: string
  path: string
  has_provenance: boolean
}

type TabId = 'split' | 'merge' | 'derived'

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
        if (s.status === 'completed' || s.status === 'failed') {
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

  const isOk = jobStatus.status === 'completed'
  const isFail = jobStatus.status === 'failed'

  return (
    <div style={{ ...s.statusBox, borderColor: isOk ? '#4caf50' : isFail ? '#e05252' : '#3a6ea5' }}>
      <div style={{ display: 'flex', alignItems: 'center', gap: 6 }}>
        <span style={{ color: isOk ? '#4caf50' : isFail ? '#e05252' : '#aaa', fontSize: 12, fontWeight: 600 }}>
          {jobStatus.status.toUpperCase()}
        </span>
        {polling && <span style={s.spinner}>⟳</span>}
      </div>
      {isOk && jobStatus.result_path && (
        <div style={s.resultPath}>
          Result: <span style={{ fontFamily: 'monospace', color: '#c8e6c9' }}>{jobStatus.result_path}</span>
        </div>
      )}
      {isFail && jobStatus.error && (
        <div style={s.errorText}>{jobStatus.error}</div>
      )}
    </div>
  )
}

function SplitTab({
  datasetPath,
  episodes,
}: {
  datasetPath: string | null
  episodes: Episode[]
}) {
  const [selectedIds, setSelectedIds] = useState<Set<number>>(new Set())
  const [targetName, setTargetName] = useState('')
  const [submitting, setSubmitting] = useState(false)
  const [submitError, setSubmitError] = useState<string | null>(null)
  const { jobStatus, polling, startPolling, reset } = useJobPoller()

  const toggleEpisode = (idx: number) => {
    setSelectedIds(prev => {
      const next = new Set(prev)
      if (next.has(idx)) next.delete(idx)
      else next.add(idx)
      return next
    })
  }

  const toggleAll = () => {
    if (selectedIds.size === episodes.length) {
      setSelectedIds(new Set())
    } else {
      setSelectedIds(new Set(episodes.map(e => e.episode_index)))
    }
  }

  const handleSubmit = async () => {
    if (!datasetPath) return
    if (selectedIds.size === 0) { setSubmitError('Select at least one episode'); return }
    if (!targetName.trim()) { setSubmitError('Enter a target dataset name'); return }

    setSubmitting(true)
    setSubmitError(null)
    reset()

    try {
      const resp = await client.post<{ job_id: string; operation: string; status: string }>('/datasets/split', {
        source_path: datasetPath,
        episode_ids: Array.from(selectedIds).sort((a, b) => a - b),
        target_name: targetName.trim(),
      })
      startPolling(resp.data.job_id)
    } catch (err: unknown) {
      const msg = (err as { response?: { data?: { detail?: string } } })?.response?.data?.detail ?? 'Split failed'
      setSubmitError(msg)
    } finally {
      setSubmitting(false)
    }
  }

  if (!datasetPath) {
    return <div style={s.emptyState}>Load a dataset first to split episodes.</div>
  }

  const allSelected = selectedIds.size === episodes.length && episodes.length > 0

  return (
    <div style={s.tabContent}>
      <div style={s.fieldLabel}>
        Episodes ({selectedIds.size}/{episodes.length} selected)
        <button style={s.selectAllBtn} onClick={toggleAll}>
          {allSelected ? 'Deselect all' : 'Select all'}
        </button>
      </div>
      <div style={s.episodeList}>
        {episodes.length === 0 && <div style={s.emptyState}>No episodes in this dataset.</div>}
        {episodes.map(ep => (
          <label key={ep.episode_index} style={s.checkRow}>
            <input
              type="checkbox"
              checked={selectedIds.has(ep.episode_index)}
              onChange={() => toggleEpisode(ep.episode_index)}
              style={s.checkbox}
            />
            <span style={s.epLabel}>
              <span style={s.epIndex}>#{ep.episode_index}</span>
              {ep.grade && <span style={{ ...s.gradeTag, color: gradeColor(ep.grade) }}>{ep.grade}</span>}
              <span style={s.epTask}>{ep.task_instruction}</span>
            </span>
          </label>
        ))}
      </div>

      <div style={s.fieldLabel}>Target dataset name</div>
      <input
        style={s.textInput}
        type="text"
        placeholder="e.g. my_dataset_split"
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
        {submitting ? 'Submitting...' : 'Split Dataset'}
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
              <span style={{ ...s.epIndex, color: '#c0d8f0' }}>{ds.name}</span>
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

function DerivedTab() {
  const [derived, setDerived] = useState<DerivedDataset[]>([])
  const [loading, setLoading] = useState(false)
  const [error, setError] = useState<string | null>(null)
  const [provenance, setProvenance] = useState<Record<string, unknown> | null>(null)
  const [provenanceName, setProvenanceName] = useState<string | null>(null)
  const [provenanceLoading, setProvenanceLoading] = useState(false)
  const [provenanceError, setProvenanceError] = useState<string | null>(null)

  const fetchDerived = useCallback(async () => {
    setLoading(true)
    setError(null)
    try {
      const resp = await client.get<DerivedDataset[]>('/datasets/derived')
      setDerived(resp.data)
    } catch {
      setError('Failed to load derived datasets')
    } finally {
      setLoading(false)
    }
  }, [])

  useEffect(() => {
    void fetchDerived()
  }, [fetchDerived])

  const viewProvenance = async (name: string) => {
    if (provenanceName === name) {
      // Toggle off
      setProvenance(null)
      setProvenanceName(null)
      return
    }
    setProvenanceLoading(true)
    setProvenanceError(null)
    setProvenance(null)
    setProvenanceName(name)
    try {
      const resp = await client.get<Record<string, unknown>>(`/datasets/derived/${encodeURIComponent(name)}/provenance`)
      setProvenance(resp.data)
    } catch {
      setProvenanceError('Failed to load provenance')
    } finally {
      setProvenanceLoading(false)
    }
  }

  return (
    <div style={s.tabContent}>
      <div style={{ display: 'flex', alignItems: 'center', justifyContent: 'space-between', marginBottom: 4 }}>
        <div style={s.fieldLabel}>Derived Datasets</div>
        <button style={s.refreshBtn} onClick={fetchDerived} disabled={loading}>
          {loading ? '...' : 'Refresh'}
        </button>
      </div>

      {error && <div style={s.errorText}>{error}</div>}

      {!loading && derived.length === 0 && !error && (
        <div style={s.emptyState}>No derived datasets yet. Use Split or Merge to create one.</div>
      )}

      <div style={{ display: 'flex', flexDirection: 'column', gap: 4 }}>
        {derived.map(ds => (
          <div key={ds.name} style={s.derivedRow}>
            <div style={s.derivedInfo}>
              <span style={s.derivedName}>{ds.name}</span>
              {ds.has_provenance && (
                <span style={s.provenanceBadge}>provenance</span>
              )}
            </div>
            {ds.has_provenance && (
              <button
                style={{ ...s.provenanceBtn, opacity: provenanceLoading && provenanceName === ds.name ? 0.6 : 1 }}
                onClick={() => viewProvenance(ds.name)}
                disabled={provenanceLoading && provenanceName === ds.name}
              >
                {provenanceName === ds.name && provenance ? 'Hide' : 'View'}
              </button>
            )}
          </div>
        ))}
      </div>

      {provenanceError && <div style={s.errorText}>{provenanceError}</div>}

      {provenanceName && provenance && (
        <div style={s.provenanceBox}>
          <div style={s.provenanceTitle}>{provenanceName} — Provenance</div>
          <pre style={s.provenancePre}>{JSON.stringify(provenance, null, 2)}</pre>
        </div>
      )}
    </div>
  )
}

function gradeColor(grade: string): string {
  if (grade === 'Good') return '#4caf50'
  if (grade === 'Bad') return '#f44336'
  return '#ffc107'
}

export function SplitMergePanel({ datasetPath, episodes }: SplitMergePanelProps) {
  const [open, setOpen] = useState(false)
  const [tab, setTab] = useState<TabId>('split')

  return (
    <div style={s.container}>
      <button style={s.header} onClick={() => setOpen(v => !v)} aria-expanded={open} aria-label="Split / Merge panel">
        <span style={s.headerTitle}>Split / Merge</span>
        <span style={s.chevron}>{open ? '▲' : '▼'}</span>
      </button>

      {open && (
        <div style={s.body}>
          <div style={s.tabs}>
            {(['split', 'merge', 'derived'] as TabId[]).map(t => (
              <button
                key={t}
                style={{ ...s.tabBtn, ...(tab === t ? s.tabBtnActive : {}) }}
                onClick={() => setTab(t)}
              >
                {t.charAt(0).toUpperCase() + t.slice(1)}
              </button>
            ))}
          </div>

          {tab === 'split' && <SplitTab datasetPath={datasetPath} episodes={episodes} />}
          {tab === 'merge' && <MergeTab />}
          {tab === 'derived' && <DerivedTab />}
        </div>
      )}
    </div>
  )
}

const s: Record<string, React.CSSProperties> = {
  container: {
    borderBottom: '1px solid #333',
  },
  header: {
    width: '100%',
    display: 'flex',
    alignItems: 'center',
    justifyContent: 'space-between',
    padding: '10px 12px',
    background: 'transparent',
    border: 'none',
    color: '#e0e0e0',
    cursor: 'pointer',
    textAlign: 'left',
  },
  headerTitle: {
    fontSize: '11px',
    fontWeight: 600,
    textTransform: 'uppercase' as const,
    letterSpacing: '0.08em',
    color: '#888',
  },
  chevron: {
    fontSize: 10,
    color: '#555',
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
    borderBottom: '1px solid #2a2a2a',
    paddingBottom: 6,
  },
  tabBtn: {
    background: 'transparent',
    border: 'none',
    color: '#666',
    fontSize: 12,
    padding: '4px 10px',
    cursor: 'pointer',
    borderRadius: '3px 3px 0 0',
  },
  tabBtnActive: {
    color: '#c0d8f0',
    background: '#2a2a2a',
  },
  tabContent: {
    display: 'flex',
    flexDirection: 'column' as const,
    gap: 8,
  },
  fieldLabel: {
    fontSize: 11,
    color: '#888',
    textTransform: 'uppercase' as const,
    letterSpacing: '0.05em',
    display: 'flex',
    alignItems: 'center',
    gap: 8,
  },
  selectAllBtn: {
    background: 'transparent',
    border: '1px solid #333',
    borderRadius: 3,
    color: '#888',
    fontSize: 10,
    padding: '2px 6px',
    cursor: 'pointer',
  },
  refreshBtn: {
    background: 'transparent',
    border: '1px solid #333',
    borderRadius: 3,
    color: '#888',
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
    background: '#1a1a1a',
    borderRadius: 4,
    border: '1px solid #2a2a2a',
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
    accentColor: '#3a6ea5',
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
    fontFamily: 'monospace',
    flexShrink: 0,
  },
  gradeTag: {
    fontSize: 10,
    fontWeight: 600,
    flexShrink: 0,
  },
  epTask: {
    color: '#aaa',
    fontSize: 11,
    overflow: 'hidden',
    textOverflow: 'ellipsis',
    whiteSpace: 'nowrap' as const,
  },
  textInput: {
    background: '#2a2a2a',
    border: '1px solid #444',
    borderRadius: 4,
    color: '#e0e0e0',
    padding: '6px 8px',
    fontSize: 12,
    outline: 'none',
    width: '100%',
    boxSizing: 'border-box' as const,
  },
  actionBtn: {
    background: '#3a6ea5',
    border: 'none',
    borderRadius: 4,
    color: '#fff',
    padding: '7px 14px',
    fontSize: 12,
    cursor: 'pointer',
    alignSelf: 'flex-start' as const,
  },
  statusBox: {
    background: '#1a1a1a',
    border: '1px solid #333',
    borderRadius: 4,
    padding: '8px 10px',
    display: 'flex',
    flexDirection: 'column' as const,
    gap: 4,
    fontSize: 12,
  },
  resultPath: {
    fontSize: 11,
    color: '#888',
    wordBreak: 'break-all' as const,
  },
  errorText: {
    fontSize: 12,
    color: '#e05252',
  },
  spinner: {
    display: 'inline-block',
    animation: 'spin 1s linear infinite',
    fontSize: 14,
  },
  empty: {
    color: '#555',
    fontSize: 12,
    padding: '6px 0',
  },
  emptyState: {
    fontSize: 13,
    color: 'var(--color-text-dim)',
    padding: '24px',
    textAlign: 'center' as const,
  },
  derivedRow: {
    display: 'flex',
    alignItems: 'center',
    justifyContent: 'space-between',
    gap: 8,
    padding: '6px 8px',
    background: '#1a1a1a',
    borderRadius: 4,
    border: '1px solid #2a2a2a',
  },
  derivedInfo: {
    display: 'flex',
    alignItems: 'center',
    gap: 8,
    minWidth: 0,
    flex: 1,
  },
  derivedName: {
    fontSize: 12,
    color: '#c0d8f0',
    fontWeight: 500,
    overflow: 'hidden',
    textOverflow: 'ellipsis',
    whiteSpace: 'nowrap' as const,
  },
  provenanceBadge: {
    fontSize: 10,
    color: '#888',
    background: '#2a2a2a',
    padding: '1px 5px',
    borderRadius: 3,
    flexShrink: 0,
  },
  provenanceBtn: {
    background: '#2a3a4a',
    border: '1px solid #3a5a7a',
    borderRadius: 3,
    color: '#c0d8f0',
    padding: '3px 8px',
    fontSize: 11,
    cursor: 'pointer',
    flexShrink: 0,
  },
  provenanceBox: {
    background: '#1a1a1a',
    border: '1px solid #2a2a2a',
    borderRadius: 4,
    padding: '8px',
    display: 'flex',
    flexDirection: 'column' as const,
    gap: 4,
  },
  provenanceTitle: {
    fontSize: 11,
    color: '#888',
    fontWeight: 600,
  },
  provenancePre: {
    margin: 0,
    fontSize: 11,
    color: '#c8e6c9',
    fontFamily: 'monospace',
    overflowX: 'auto' as const,
    maxHeight: 200,
    overflowY: 'auto' as const,
    whiteSpace: 'pre-wrap' as const,
    wordBreak: 'break-all' as const,
  },
}
