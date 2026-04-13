import { useState, useEffect, useCallback } from 'react'
import { useDataset } from '../hooks/useDataset'
import client from '../api/client'
import type { DatasetInfo } from '../types'

interface MountDetail {
  repo_id: string
  mount_point: string
  mounted_at: string
}

interface HubSyncStatus {
  mount_details: Record<string, { mount_point: string; mounted_at: string }>
  initialized: boolean
}

interface DatasetLoaderProps {
  onDatasetLoaded: (dataset: DatasetInfo) => void
}

export function DatasetLoader({ onDatasetLoaded }: DatasetLoaderProps) {
  const [mountDetails, setMountDetails] = useState<MountDetail[]>([])
  const [listError, setListError] = useState<string | null>(null)
  const [manualPath, setManualPath] = useState('')
  const { dataset, loading, error, loadDataset } = useDataset()

  const fetchMountedRepos = useCallback(async () => {
    try {
      const resp = await client.get<HubSyncStatus>('/hf-sync/status')
      const details = Object.entries(resp.data.mount_details).map(([repo_id, d]) => ({
        repo_id,
        mount_point: d.mount_point,
        mounted_at: d.mounted_at,
      }))
      setMountDetails(details)
      setListError(null)
    } catch {
      setListError('Failed to fetch mounted repos')
    }
  }, [])

  useEffect(() => {
    void fetchMountedRepos()
  }, [fetchMountedRepos])

  // Notify parent when dataset changes
  useEffect(() => {
    if (dataset) {
      onDatasetLoaded(dataset)
    }
  }, [dataset, onDatasetLoaded])

  const handleSelect = async (detail: MountDetail) => {
    await loadDataset(detail.mount_point)
  }

  const handleManualLoad = async () => {
    if (!manualPath.trim()) return
    await loadDataset(manualPath.trim())
    await fetchMountedRepos()
  }

  const handleKeyDown = (e: React.KeyboardEvent) => {
    if (e.key === 'Enter') handleManualLoad()
  }

  return (
    <div style={styles.container}>
      <div style={styles.title}>Datasets</div>

      <div style={styles.inputRow}>
        <input
          style={styles.input}
          type="text"
          placeholder="Dataset path or HF repo..."
          value={manualPath}
          onChange={e => setManualPath(e.target.value)}
          onKeyDown={handleKeyDown}
          disabled={loading}
        />
        <button
          style={{ ...styles.button, opacity: loading ? 0.6 : 1 }}
          onClick={handleManualLoad}
          disabled={loading}
        >
          {loading ? '...' : 'Load'}
        </button>
      </div>

      {listError && <div style={styles.error}>{listError}</div>}

      <div className="conversion-repo-list">
        {mountDetails.map(detail => {
          const isSelected = dataset?.path === detail.mount_point
          return (
            <div
              key={detail.repo_id}
              className={`conversion-repo-item${isSelected ? ' selected' : ''}`}
              style={{ opacity: loading ? 0.6 : 1, pointerEvents: loading ? 'none' : 'auto' }}
              onClick={() => handleSelect(detail)}
            >
              <span className="conversion-repo-dot mounted" />
              <div>
                <div className="conversion-repo-name">{detail.repo_id}</div>
                <div className="conversion-repo-mount">{detail.mount_point}</div>
              </div>
              {isSelected && <span className="conversion-repo-check">✓</span>}
            </div>
          )
        })}
        {mountDetails.length === 0 && (
          <div style={styles.message}>No mounted repos. Sync HF Hub below.</div>
        )}
        <div className="conversion-repo-create" onClick={() => {
          const id = prompt('New repo_id (e.g. org/name):')
          if (id?.trim()) setManualPath(id.trim())
        }}>
          <span>+</span> Create new repository
        </div>
      </div>

      {loading && <div style={styles.message}>Loading...</div>}
      {error && <div style={styles.error}>{error}</div>}

      {dataset && (
        <div style={styles.info}>
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
    marginBottom: '8px',
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
    background: '#89b4fa',
    border: 'none',
    borderRadius: '4px',
    color: '#fff',
    padding: '6px 12px',
    fontSize: '13px',
    cursor: 'pointer',
    whiteSpace: 'nowrap',
  },
  message: {
    padding: '8px 0',
    color: '#666',
    fontSize: '12px',
  },
  error: {
    marginTop: '6px',
    color: '#f38ba8',
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
    color: '#a6e3a1',
    fontFamily: 'monospace',
  },
}
