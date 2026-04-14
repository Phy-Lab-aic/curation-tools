import type { Episode } from '../types'

interface EpisodeListProps {
  episodes: Episode[]
  loading: boolean
  error: string | null
  onEpisodeSelect: (episode: Episode) => void
  selectedIndex: number | null
}

function gradeDotClass(grade: string | null): string {
  if (grade === 'good')   return 'good'
  if (grade === 'normal') return 'normal'
  if (grade === 'bad')    return 'bad'
  return 'none'
}

export function EpisodeList({
  episodes, loading, error, onEpisodeSelect, selectedIndex,
}: EpisodeListProps) {
  const gradedCount = episodes.filter(e => e.grade).length

  return (
    <>
      <div className="episode-sidebar-header">
        <span className="episode-sidebar-title">Episodes</span>
        <span className="episode-progress-count">{gradedCount} / {episodes.length}</span>
      </div>

      {loading && (
        <div style={{ padding: '10px', fontSize: 11, color: 'var(--text-muted)' }}>
          Loading...
        </div>
      )}
      {error && (
        <div style={{ padding: '10px', fontSize: 11, color: 'var(--c-red)' }}>
          {error}
        </div>
      )}

      <div className="episode-list">
        {episodes.map(ep => (
          <div
            key={ep.episode_index}
            className={`episode-item${ep.episode_index === selectedIndex ? ' active' : ''}`}
            onClick={() => onEpisodeSelect(ep)}
          >
            <span className={`episode-grade-dot ${gradeDotClass(ep.grade)}`} />
            <span className="episode-item-idx">ep_{String(ep.episode_index).padStart(3, '0')}</span>
            <span className="episode-item-len">{ep.length}f</span>
          </div>
        ))}
        {!loading && episodes.length === 0 && (
          <div style={{ padding: '10px', fontSize: 11, color: 'var(--text-muted)' }}>
            No episodes found.
          </div>
        )}
      </div>
    </>
  )
}
