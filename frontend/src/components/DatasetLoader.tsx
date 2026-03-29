import { useState, useEffect } from 'react'
import { useDataset } from '../hooks/useDataset'
import type { DatasetInfo } from '../types'

interface DatasetLoaderProps {
  onDatasetLoaded: (dataset: DatasetInfo) => void
}

export function DatasetLoader({ onDatasetLoaded }: DatasetLoaderProps) {
  const [path, setPath] = useState('')
  const { dataset, loading, error, loadDataset } = useDataset()

  const handleLoad = async () => {
    if (!path.trim()) return
    await loadDataset(path.trim())
  }

  const handleKeyDown = (e: React.KeyboardEvent) => {
    if (e.key === 'Enter') handleLoad()
  }

  // Notify parent when dataset changes
  useEffect(() => {
    if (dataset) {
      onDatasetLoaded(dataset)
    }
  }, [dataset, onDatasetLoaded])

  return (
    <div style={styles.container}>
      <div style={styles.title}>Dataset</div>
      <div style={styles.inputRow}>
        <input
          style={styles.input}
          type="text"
          placeholder="Dataset path or HF repo..."
          value={path}
          onChange={e => setPath(e.target.value)}
          onKeyDown={handleKeyDown}
          disabled={loading}
        />
        <button
          style={{ ...styles.button, opacity: loading ? 0.6 : 1 }}
          onClick={handleLoad}
          disabled={loading}
        >
          {loading ? '...' : 'Load'}
        </button>
      </div>
      {error && <div style={styles.error}>{error}</div>}
      {dataset && (
        <div style={styles.info}>
          <div style={styles.infoRow}>
            <span style={styles.label}>Name</span>
            <span style={styles.value}>{dataset.name}</span>
          </div>
          <div style={styles.infoRow}>
            <span style={styles.label}>Episodes</span>
            <span style={styles.value}>{dataset.total_episodes}</span>
          </div>
          <div style={styles.infoRow}>
            <span style={styles.label}>Tasks</span>
            <span style={styles.value}>{dataset.total_tasks}</span>
          </div>
          <div style={styles.infoRow}>
            <span style={styles.label}>FPS</span>
            <span style={styles.value}>{dataset.fps}</span>
          </div>
          {dataset.robot_type && (
            <div style={styles.infoRow}>
              <span style={styles.label}>Robot</span>
              <span style={styles.value}>{dataset.robot_type}</span>
            </div>
          )}
        </div>
      )}
    </div>
  )
}

const styles: Record<string, React.CSSProperties> = {
  container: {
    padding: '12px',
    borderBottom: '1px solid #333',
  },
  title: {
    fontSize: '11px',
    fontWeight: 600,
    textTransform: 'uppercase',
    letterSpacing: '0.08em',
    color: '#888',
    marginBottom: '8px',
  },
  inputRow: {
    display: 'flex',
    gap: '6px',
  },
  input: {
    flex: 1,
    background: '#2a2a2a',
    border: '1px solid #444',
    borderRadius: '4px',
    color: '#e0e0e0',
    padding: '6px 8px',
    fontSize: '13px',
    outline: 'none',
  },
  button: {
    background: '#3a6ea5',
    border: 'none',
    borderRadius: '4px',
    color: '#fff',
    padding: '6px 12px',
    fontSize: '13px',
    cursor: 'pointer',
    whiteSpace: 'nowrap',
  },
  error: {
    marginTop: '6px',
    color: '#e05252',
    fontSize: '12px',
  },
  info: {
    marginTop: '8px',
    background: '#222',
    borderRadius: '4px',
    padding: '8px',
  },
  infoRow: {
    display: 'flex',
    justifyContent: 'space-between',
    fontSize: '12px',
    marginBottom: '3px',
  },
  label: {
    color: '#888',
  },
  value: {
    color: '#c8e6c9',
    fontFamily: 'monospace',
  },
}
