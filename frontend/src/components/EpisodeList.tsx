import { useMemo, useEffect, useRef, memo, useState } from 'react'
import type { Episode, GradeFilter } from '../types'

interface EpisodeListProps {
  episodes: Episode[]
  loading: boolean
  error: string | null
  onEpisodeSelect: (episode: Episode) => void
  selectedIndex: number | null
  initialGradeFilter?: GradeFilter
  filterChip?: { label: string; onClear: () => void } | null
}

function gradeDotClass(grade: string | null): string {
  if (grade === 'good')   return 'good'
  if (grade === 'normal') return 'normal'
  if (grade === 'bad')    return 'bad'
  return 'none'
}

export const EpisodeList = memo(function EpisodeList({
  episodes, loading, error, onEpisodeSelect, selectedIndex,
  initialGradeFilter, filterChip,
}: EpisodeListProps) {
  const [gradeFilter, setGradeFilter] = useState<GradeFilter>(initialGradeFilter ?? 'all')

  // Sync filter when navigated to with a new initialGradeFilter (e.g., from Grade cards)
  useEffect(() => {
    if (initialGradeFilter) setGradeFilter(initialGradeFilter)
  }, [initialGradeFilter])

  const gradedCount = useMemo(() => episodes.filter(e => e.grade).length, [episodes])

  const filteredEpisodes = useMemo(() => {
    if (gradeFilter === 'all') return episodes
    if (gradeFilter === 'ungraded') return episodes.filter(e => !e.grade)
    return episodes.filter(e => e.grade === gradeFilter)
  }, [episodes, gradeFilter])

  const selectedItemRef = useRef<HTMLDivElement>(null)

  useEffect(() => {
    selectedItemRef.current?.scrollIntoView({ block: 'nearest', behavior: 'smooth' })
  }, [selectedIndex])

  return (
    <>
      <div className="episode-sidebar-header">
        <span className="episode-sidebar-title">Episodes</span>
        <span className="episode-progress-count">{gradedCount} / {episodes.length}</span>
      </div>

      {filterChip && (
        <div className="filter-chip-bar">
          <span className="filter-chip">
            {filterChip.label}
            <button className="filter-chip-clear" onClick={filterChip.onClear}>&times;</button>
          </span>
        </div>
      )}

      <div className="grade-filter-bar">
        {([
          ['all', 'All'],
          ['good', 'Good'],
          ['normal', 'Normal'],
          ['bad', 'Bad'],
          ['ungraded', 'Ungraded'],
        ] as [GradeFilter, string][]).map(([value, label]) => (
          <button
            key={value}
            className={`grade-filter-btn${gradeFilter === value ? ` active ${value}` : ''}`}
            onClick={() => setGradeFilter(value)}
          >
            {label}
            <span className="grade-filter-count">
              {value === 'all' ? episodes.length
                : value === 'ungraded' ? episodes.filter(e => !e.grade).length
                : episodes.filter(e => e.grade === value).length}
            </span>
          </button>
        ))}
      </div>

      {loading && (
        <div className="loading-pulse" style={{ padding: '10px', fontSize: 11, color: 'var(--text-muted)' }}>
          Loading...
        </div>
      )}
      {error && (
        <div style={{ padding: '10px', fontSize: 11, color: 'var(--c-red)' }}>
          {error}
        </div>
      )}

      <div className="episode-list">
        {filteredEpisodes.map(ep => {
          const isSelected = ep.episode_index === selectedIndex
          return (
            <div
              key={ep.episode_index}
              ref={isSelected ? selectedItemRef : null}
              className={`episode-item${isSelected ? ' active' : ''}`}
              onClick={() => onEpisodeSelect(ep)}
            >
              <span className={`episode-grade-dot ${gradeDotClass(ep.grade)}`} />
              <span className="episode-item-idx">ep_{String(ep.episode_index).padStart(3, '0')}</span>
            </div>
          )
        })}
        {!loading && filteredEpisodes.length === 0 && (
          <div style={{ padding: '10px', fontSize: 11, color: 'var(--text-muted)' }}>
            {episodes.length === 0 ? 'No episodes found.' : 'No matching episodes.'}
          </div>
        )}
      </div>
    </>
  )
})
