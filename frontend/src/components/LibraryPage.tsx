import { useEffect, useState } from 'react'
import { useSources } from '../hooks/useCells'
import type { DatasetSourceInfo } from '../types'

interface LibraryPageProps {
  onSelectSource: (source: DatasetSourceInfo) => void
}

export function LibraryPage({ onSelectSource }: LibraryPageProps) {
  const { sources, loading, error, fetchSources } = useSources()
  const [search, setSearch] = useState('')

  useEffect(() => { void fetchSources() }, [fetchSources])

  const filtered = sources.filter(source =>
    source.name.toLowerCase().includes(search.toLowerCase())
  )

  return (
    <div className="library-page">
      <div className="library-filter-bar">
        <input
          className="library-search"
          placeholder="Search sources..."
          value={search}
          onChange={e => setSearch(e.target.value)}
        />
      </div>

      {loading && <div className="loading-pulse" style={{ color: 'var(--text-muted)', fontSize: 12 }}>Loading registered sources...</div>}
      {error && <div style={{ color: 'var(--c-red)', fontSize: 12 }}>{error}</div>}

      <div className="cell-grid">
        {filtered.map(source => (
          <div
            key={source.path}
            className="cell-card"
            onClick={() => onSelectSource(source)}
          >
            <div className="cell-card-name">
              <span className={`cell-status-dot ${source.active ? 'active' : 'idle'}`} />
              {source.name}
            </div>
            <div className="cell-card-meta">
              {source.cell_count} cell{source.cell_count !== 1 ? 's' : ''}
            </div>
            <div className="cell-card-meta" style={{ marginTop: 4, wordBreak: 'break-all' }}>
              {source.path}
            </div>
          </div>
        ))}
      </div>

      {!loading && filtered.length === 0 && (
        <div style={{ color: 'var(--text-muted)', fontSize: 12, padding: '20px 0' }}>
          No registered sources found.
        </div>
      )}
    </div>
  )
}
