import { useEffect, useState } from 'react'
import { sourceContentMode } from '../appChrome'
import { useCells } from '../hooks/useCells'
import { CellPage } from './CellPage'
import type { CellInfo, DatasetSummary } from '../types'

interface SourcePageProps {
  sourceName: string
  sourcePath: string
  onSelectCell: (cell: CellInfo) => void
  onSelectDataset: (dataset: DatasetSummary) => void
}

export function SourcePage({ sourceName, sourcePath, onSelectCell, onSelectDataset }: SourcePageProps) {
  const { cells, loading, error, fetchCells } = useCells()
  const [search, setSearch] = useState('')

  useEffect(() => { void fetchCells(sourcePath) }, [fetchCells, sourcePath])

  if (!loading && !error && sourceContentMode(cells.length) === 'datasets') {
    return (
      <CellPage
        cellName={sourceName}
        cellPath={sourcePath}
        onSelectDataset={onSelectDataset}
      />
    )
  }

  const filtered = cells.filter(cell =>
    cell.name.toLowerCase().includes(search.toLowerCase())
  )

  return (
    <div className="library-page">
      <div className="library-filter-bar">
        <input
          className="library-search"
          placeholder={`Search cells in ${sourceName}...`}
          value={search}
          onChange={e => setSearch(e.target.value)}
        />
      </div>

      <div style={{ color: 'var(--text-muted)', fontSize: 12, marginBottom: 16 }}>
        Source root: <code>{sourcePath}</code>
      </div>

      {loading && <div className="loading-pulse" style={{ color: 'var(--text-muted)', fontSize: 12 }}>Scanning cells...</div>}
      {error && <div style={{ color: 'var(--c-red)', fontSize: 12 }}>{error}</div>}

      <div className="cell-grid">
        {filtered.map(cell => (
          <div
            key={cell.path}
            className="cell-card"
            onClick={() => onSelectCell(cell)}
          >
            <div className="cell-card-name">
              <span className={`cell-status-dot ${cell.active ? 'active' : 'idle'}`} />
              {cell.name}
            </div>
            <div className="cell-card-meta">
              {cell.dataset_count} dataset{cell.dataset_count !== 1 ? 's' : ''}
            </div>
          </div>
        ))}
      </div>

      {!loading && filtered.length === 0 && (
        <div style={{ color: 'var(--text-muted)', fontSize: 12, padding: '20px 0' }}>
          No cells found under <code>{sourceName}</code>.
        </div>
      )}
    </div>
  )
}
