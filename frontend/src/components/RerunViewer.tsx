import { useEffect, useState, useRef } from 'react'
import client from '../api/client'

interface RerunViewerProps {
  episodeIndex: number | null
}

export function RerunViewer({ episodeIndex }: RerunViewerProps) {
  const [loading, setLoading] = useState(false)
  const [error, setError] = useState<string | null>(null)
  const prevIndexRef = useRef<number | null>(null)

  useEffect(() => {
    if (episodeIndex === null || episodeIndex === prevIndexRef.current) return
    prevIndexRef.current = episodeIndex

    setLoading(true)
    setError(null)

    client.post(`/rerun/visualize/${episodeIndex}`)
      .then(() => {
        setLoading(false)
      })
      .catch(err => {
        setError(err instanceof Error ? err.message : 'Visualization failed')
        setLoading(false)
      })
  }, [episodeIndex])

  return (
    <div style={styles.container}>
      <div style={styles.toolbar}>
        <span style={styles.title}>Rerun Viewer</span>
        {episodeIndex !== null && (
          <span style={styles.epLabel}>Episode #{episodeIndex}</span>
        )}
        {loading && <span style={styles.loading}>Loading visualization...</span>}
        {error && <span style={styles.error}>{error}</span>}
      </div>
      <iframe
        style={styles.iframe}
        src={import.meta.env.VITE_RERUN_URL ?? "http://localhost:9090"}
        title="Rerun Viewer"
        sandbox="allow-scripts allow-same-origin"
        allowFullScreen
      />
    </div>
  )
}

const styles: Record<string, React.CSSProperties> = {
  container: {
    display: 'flex',
    flexDirection: 'column',
    flex: 1,
    overflow: 'hidden',
    background: 'var(--panel3)',
  },
  toolbar: {
    display: 'flex',
    alignItems: 'center',
    gap: '12px',
    padding: '8px 12px',
    background: 'var(--panel2)',
    borderBottom: '1px solid var(--border3)',
    flexShrink: 0,
  },
  title: {
    fontSize: '11px',
    fontWeight: 600,
    textTransform: 'uppercase',
    letterSpacing: '0.08em',
    color: 'var(--text-muted)',
  },
  epLabel: {
    fontSize: '12px',
    color: 'var(--interactive)',
    fontFamily: 'var(--font-mono)',
  },
  loading: {
    fontSize: '12px',
    color: 'var(--c-yellow)',
  },
  error: {
    fontSize: '12px',
    color: 'var(--c-red)',
  },
  iframe: {
    flex: 1,
    border: 'none',
    width: '100%',
  },
}
