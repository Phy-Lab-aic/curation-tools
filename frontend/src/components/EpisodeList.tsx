import { useEffect } from 'react'
import { useEpisodes } from '../hooks/useEpisodes'
import type { Episode } from '../types'

const GRADE_COLORS: Record<string, string> = {
  A: '#4caf50',
  B: '#8bc34a',
  C: '#ffc107',
  D: '#ff9800',
  F: '#f44336',
}

interface EpisodeListProps {
  onEpisodeSelect: (episode: Episode) => void
  selectedIndex: number | null
  refreshKey: number
}

export function EpisodeList({ onEpisodeSelect, selectedIndex, refreshKey }: EpisodeListProps) {
  const { episodes, loading, error, fetchEpisodes, selectEpisode } = useEpisodes()

  useEffect(() => {
    void fetchEpisodes()
  }, [fetchEpisodes, refreshKey])

  const handleClick = (episode: Episode) => {
    selectEpisode(episode.episode_index)
    onEpisodeSelect(episode)
  }

  if (loading && episodes.length === 0) {
    return <div style={styles.message}>Loading episodes...</div>
  }

  if (error) {
    return <div style={styles.errorMessage}>{error}</div>
  }

  if (episodes.length === 0) {
    return <div style={styles.message}>No dataset loaded</div>
  }

  return (
    <div style={styles.container}>
      <div style={styles.header}>
        <span style={styles.headerTitle}>Episodes</span>
        <span style={styles.count}>{episodes.length}</span>
      </div>
      <div style={styles.list}>
        {episodes.map(ep => (
          <div
            key={ep.episode_index}
            style={{
              ...styles.item,
              background: selectedIndex === ep.episode_index ? '#2a3a4a' : 'transparent',
              borderLeft: selectedIndex === ep.episode_index ? '2px solid #3a6ea5' : '2px solid transparent',
            }}
            onClick={() => handleClick(ep)}
          >
            <div style={styles.itemTop}>
              <span style={styles.index}>#{ep.episode_index}</span>
              {ep.grade && (
                <span style={{ ...styles.grade, background: GRADE_COLORS[ep.grade] ?? '#666' }}>
                  {ep.grade}
                </span>
              )}
            </div>
            <div style={styles.itemBottom}>
              <span style={styles.length}>{ep.length} frames</span>
              {ep.tags.length > 0 && (
                <span style={styles.tagCount}>{ep.tags.length} tags</span>
              )}
            </div>
          </div>
        ))}
      </div>
    </div>
  )
}

const styles: Record<string, React.CSSProperties> = {
  container: {
    display: 'flex',
    flexDirection: 'column',
    flex: 1,
    overflow: 'hidden',
  },
  header: {
    display: 'flex',
    justifyContent: 'space-between',
    alignItems: 'center',
    padding: '8px 12px',
    borderBottom: '1px solid #333',
  },
  headerTitle: {
    fontSize: '11px',
    fontWeight: 600,
    textTransform: 'uppercase',
    letterSpacing: '0.08em',
    color: '#888',
  },
  count: {
    fontSize: '11px',
    color: '#666',
    background: '#2a2a2a',
    padding: '1px 6px',
    borderRadius: '10px',
  },
  list: {
    overflowY: 'auto',
    flex: 1,
  },
  item: {
    padding: '8px 12px',
    cursor: 'pointer',
    borderBottom: '1px solid #222',
    transition: 'background 0.1s',
  },
  itemTop: {
    display: 'flex',
    justifyContent: 'space-between',
    alignItems: 'center',
    marginBottom: '3px',
  },
  index: {
    fontFamily: 'monospace',
    fontSize: '13px',
    color: '#c0d8f0',
  },
  grade: {
    fontSize: '11px',
    fontWeight: 700,
    color: '#fff',
    padding: '1px 6px',
    borderRadius: '3px',
  },
  itemBottom: {
    display: 'flex',
    justifyContent: 'space-between',
    fontSize: '11px',
    color: '#666',
  },
  length: {
    color: '#888',
  },
  tagCount: {
    color: '#5a8ab0',
  },
  message: {
    padding: '16px 12px',
    color: '#666',
    fontSize: '13px',
  },
  errorMessage: {
    padding: '16px 12px',
    color: '#e05252',
    fontSize: '13px',
  },
}
