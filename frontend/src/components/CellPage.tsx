import { useEffect } from 'react'
import { useDatasets } from '../hooks/useCells'
import type { DatasetSummary } from '../types'

interface CellPageProps {
  cellName: string
  cellPath: string
  onSelectDataset: (dataset: DatasetSummary) => void
}

export function CellPage({ cellName, cellPath, onSelectDataset }: CellPageProps) {
  const { datasets, loading, error, fetchDatasets } = useDatasets()

  useEffect(() => { void fetchDatasets(cellPath) }, [cellPath, fetchDatasets])

  return (
    <div className="cell-page">
      <div style={{ marginBottom: 16, fontSize: 12, color: 'var(--text-muted)' }}>
        {datasets.length} dataset{datasets.length !== 1 ? 's' : ''} in {cellName}
      </div>

      {loading && <div style={{ color: 'var(--text-muted)', fontSize: 12 }}>Loading...</div>}
      {error && <div style={{ color: 'var(--c-red)', fontSize: 12 }}>{error}</div>}

      <div className="dataset-grid">
        {datasets.map(ds => {
          const pct = ds.total_episodes > 0
            ? Math.round((ds.graded_count / ds.total_episodes) * 100)
            : 0
          const fillColor = pct === 100 ? 'var(--c-green)' : 'var(--accent)'

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
                <span>{ds.total_episodes} eps</span>
                <span>{ds.fps} fps</span>
              </div>
              <div className="dataset-card-progress">
                <div
                  className="dataset-card-progress-fill"
                  style={{ width: `${pct}%`, background: fillColor }}
                />
              </div>
            </div>
          )
        })}
      </div>
    </div>
  )
}
