import { useEffect, useState } from 'react'
import { useCells } from '../hooks/useCells'
import type { CellInfo } from '../types'

interface LibraryPageProps {
  onSelectCell: (cell: CellInfo) => void
}

export function LibraryPage({ onSelectCell }: LibraryPageProps) {
  const { cells, loading, error, fetchCells } = useCells()
  const [search, setSearch] = useState('')

  useEffect(() => { void fetchCells() }, [fetchCells])

  const filtered = cells.filter(c =>
    c.name.toLowerCase().includes(search.toLowerCase())
  )

  // Group by mount_root
  const byRoot = filtered.reduce<Record<string, CellInfo[]>>((acc, cell) => {
    if (!acc[cell.mount_root]) acc[cell.mount_root] = []
    acc[cell.mount_root].push(cell)
    return acc
  }, {})

  return (
    <div className="library-page">
      <div className="library-filter-bar">
        <input
          className="library-search"
          placeholder="Search cells..."
          value={search}
          onChange={e => setSearch(e.target.value)}
        />
      </div>

      {loading && <div style={{ color: 'var(--text-muted)', fontSize: 12 }}>Scanning mounts...</div>}
      {error && <div style={{ color: 'var(--c-red)', fontSize: 12 }}>{error}</div>}

      {Object.entries(byRoot).map(([root, rootCells]) => (
        <div key={root}>
          <div className="library-section-header">{root}</div>
          <div className="cell-grid">
            {rootCells.map(cell => (
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
        </div>
      ))}

      {!loading && cells.length === 0 && (
        <div style={{ color: 'var(--text-muted)', fontSize: 12, padding: '20px 0' }}>
          No cells found. Check <code>CURATION_ALLOWED_DATASET_ROOTS</code> config.
        </div>
      )}
    </div>
  )
}
