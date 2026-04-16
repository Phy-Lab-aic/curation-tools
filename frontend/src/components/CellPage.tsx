import { useEffect } from 'react'
import { useDatasets } from '../hooks/useCells'
import type { DatasetSummary } from '../types'

interface CellPageProps {
  cellName: string
  cellPath: string
  onSelectDataset: (dataset: DatasetSummary) => void
}

function formatDuration(totalSeconds: number): string {
  const hours = Math.floor(totalSeconds / 3600)
  const minutes = Math.floor((totalSeconds % 3600) / 60)
  const secs = Math.floor(totalSeconds % 60)
  if (hours > 0) return `${hours}h ${minutes}m ${secs}s`
  if (minutes > 0) return `${minutes}m ${secs}s`
  return `${secs}s`
}

export function CellPage({ cellName, cellPath, onSelectDataset }: CellPageProps) {
  const { datasets, loading, error, fetchDatasets } = useDatasets()

  useEffect(() => { void fetchDatasets(cellPath) }, [cellPath, fetchDatasets])

  return (
    <div className="cell-page">
      <div style={{ marginBottom: 16, fontSize: 12, color: 'var(--text-muted)' }}>
        {datasets.length} dataset{datasets.length !== 1 ? 's' : ''} in {cellName}
      </div>

      {loading && <div className="loading-pulse" style={{ color: 'var(--text-muted)', fontSize: 12 }}>Loading datasets...</div>}
      {error && <div style={{ color: 'var(--c-red)', fontSize: 12 }}>{error}</div>}

      <div className="dataset-grid">
        {datasets.map(ds => {
          const total = ds.total_episodes || 1
          const goodPct = (ds.good_count / total) * 100
          const normalPct = (ds.normal_count / total) * 100
          const badPct = (ds.bad_count / total) * 100
          const ungradedPct = ((total - ds.good_count - ds.normal_count - ds.bad_count) / total) * 100

          return (
            <div
              key={ds.path}
              className="dataset-card"
              onClick={() => onSelectDataset(ds)}
            >
              {ds.robot_type && (
                <div style={{ fontSize: 9, color: 'var(--text-dim)', textTransform: 'uppercase', letterSpacing: '0.06em', marginBottom: 3 }}>
                  {ds.robot_type}
                </div>
              )}
              <div className="dataset-card-name">{ds.name}</div>
              <div className="dataset-card-meta">
                <span>{ds.total_episodes} episodes</span>
                <span>{formatDuration(ds.total_duration_sec)}</span>
              </div>
              {(ds.good_duration_sec > 0 || ds.normal_duration_sec > 0 || ds.bad_duration_sec > 0) && (
                <div className="dataset-card-meta" style={{ marginTop: 2 }}>
                  {ds.good_duration_sec > 0 && <span style={{ color: 'var(--c-green)' }}>Good {formatDuration(ds.good_duration_sec)}</span>}
                  {ds.normal_duration_sec > 0 && <span style={{ color: 'var(--c-yellow)' }}>Normal {formatDuration(ds.normal_duration_sec)}</span>}
                  {ds.bad_duration_sec > 0 && <span style={{ color: 'var(--c-red)' }}>Bad {formatDuration(ds.bad_duration_sec)}</span>}
                </div>
              )}
              <div className="dataset-card-grade-bar">
                {goodPct > 0 && <div className="grade-seg" style={{ width: `${goodPct}%`, background: 'var(--c-green)' }} />}
                {normalPct > 0 && <div className="grade-seg" style={{ width: `${normalPct}%`, background: 'var(--c-yellow)' }} />}
                {badPct > 0 && <div className="grade-seg" style={{ width: `${badPct}%`, background: 'var(--c-red)' }} />}
                {ungradedPct > 0 && <div className="grade-seg" style={{ width: `${ungradedPct}%`, background: 'var(--border2)' }} />}
              </div>
            </div>
          )
        })}
      </div>
    </div>
  )
}
