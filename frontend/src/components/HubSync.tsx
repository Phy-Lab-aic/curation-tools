import { useState, useEffect, useCallback } from 'react'
import client from '../api/client'

interface MountDetail {
  repo_id: string
  mount_point: string
  mounted_at: string
}

interface HubSyncStatus {
  org: string
  mounted_repos: string[]
  mount_details: MountDetail[]
  last_scan: string | null
  errors: string[]
  initialized: boolean
}

interface ScanResult {
  scanned: number
  new_mounts: string[]
  already_mounted: string[]
  failed: Record<string, string>
}

function timeAgo(isoString: string): string {
  const diff = Date.now() - new Date(isoString).getTime()
  const seconds = Math.floor(diff / 1000)
  if (seconds < 60) return `${seconds}s ago`
  const minutes = Math.floor(seconds / 60)
  if (minutes < 60) return `${minutes}m ago`
  const hours = Math.floor(minutes / 60)
  if (hours < 24) return `${hours}h ago`
  return `${Math.floor(hours / 24)}d ago`
}

export function HubSync() {
  const [open, setOpen] = useState(false)
  const [status, setStatus] = useState<HubSyncStatus | null>(null)
  const [statusError, setStatusError] = useState<string | null>(null)
  const [scanning, setScanning] = useState(false)
  const [scanResult, setScanResult] = useState<ScanResult | null>(null)
  const [scanError, setScanError] = useState<string | null>(null)
  const [unmounting, setUnmounting] = useState<Set<string>>(new Set())
  const [errorsOpen, setErrorsOpen] = useState(false)

  const fetchStatus = useCallback(async () => {
    try {
      const resp = await client.get<HubSyncStatus>('/hf-sync/status')
      setStatus(resp.data)
      setStatusError(null)
    } catch {
      setStatusError('Failed to fetch HF sync status')
    }
  }, [])

  useEffect(() => {
    if (!open) return
    void fetchStatus()
  }, [open, fetchStatus])

  const handleScan = async () => {
    setScanning(true)
    setScanResult(null)
    setScanError(null)
    try {
      const resp = await client.post<ScanResult>('/hf-sync/scan')
      setScanResult(resp.data)
      await fetchStatus()
    } catch {
      setScanError('Scan failed')
    } finally {
      setScanning(false)
    }
  }

  const handleUnmount = async (repoId: string) => {
    setUnmounting(prev => new Set(prev).add(repoId))
    try {
      await client.post(`/hf-sync/repos/${encodeURIComponent(repoId)}/unmount`)
      await fetchStatus()
    } catch {
      // ignore — status will reflect reality
    } finally {
      setUnmounting(prev => {
        const next = new Set(prev)
        next.delete(repoId)
        return next
      })
    }
  }

  return (
    <div style={s.container}>
      {/* Header / toggle */}
      <button style={s.header} onClick={() => setOpen(v => !v)}>
        <span style={s.headerTitle}>HF Hub Sync</span>
        <span style={s.headerMeta}>
          {status && (
            <span style={{ color: status.initialized ? '#8bc34a' : '#ffc107', marginRight: 8, fontSize: 11 }}>
              {status.initialized ? 'active' : 'idle'}
            </span>
          )}
          {status && (
            <span style={{ color: '#888', fontSize: 11, marginRight: 8 }}>
              {status.mounted_repos.length} repos
            </span>
          )}
          <span style={s.chevron}>{open ? '▲' : '▼'}</span>
        </span>
      </button>

      {open && (
        <div style={s.body}>
          {statusError && <div style={s.error}>{statusError}</div>}

          {status && (
            <>
              {/* Stats row */}
              <div style={s.statsRow}>
                <div style={s.stat}>
                  <span style={s.statLabel}>Org</span>
                  <span style={s.statValue}>{status.org || '—'}</span>
                </div>
                <div style={s.stat}>
                  <span style={s.statLabel}>Mounted</span>
                  <span style={s.statValue}>{status.mounted_repos.length}</span>
                </div>
                <div style={s.stat}>
                  <span style={s.statLabel}>Last scan</span>
                  <span style={s.statValue}>
                    {status.last_scan ? timeAgo(status.last_scan) : '—'}
                  </span>
                </div>
              </div>

              {/* Scan button */}
              <button
                style={{ ...s.scanBtn, opacity: scanning ? 0.6 : 1 }}
                onClick={handleScan}
                disabled={scanning}
              >
                {scanning ? (
                  <span style={s.spinner}>⟳</span>
                ) : null}
                {scanning ? 'Scanning...' : 'Scan Now'}
              </button>

              {scanError && <div style={s.error}>{scanError}</div>}

              {scanResult && (
                <div style={s.scanResult}>
                  <span style={{ color: '#8bc34a' }}>+{scanResult.new_mounts.length} new</span>
                  {' · '}
                  <span style={{ color: '#888' }}>{scanResult.already_mounted.length} already mounted</span>
                  {Object.keys(scanResult.failed).length > 0 && (
                    <>
                      {' · '}
                      <span style={{ color: '#e05252' }}>{Object.keys(scanResult.failed).length} failed</span>
                    </>
                  )}
                </div>
              )}

              {/* Mounted repos table */}
              {status.mount_details.length > 0 && (
                <div style={s.section}>
                  <div style={s.sectionTitle}>Mounted Repos</div>
                  <div style={s.repoList}>
                    {status.mount_details.map(detail => (
                      <div key={detail.repo_id} style={s.repoRow}>
                        <div style={s.repoInfo}>
                          <div style={s.repoName}>{detail.repo_id}</div>
                          <div style={s.repoMeta}>
                            <span style={s.repoMount}>{detail.mount_point}</span>
                            <span style={s.repoDot}>·</span>
                            <span style={s.repoTime}>{timeAgo(detail.mounted_at)}</span>
                          </div>
                        </div>
                        <button
                          style={{
                            ...s.unmountBtn,
                            opacity: unmounting.has(detail.repo_id) ? 0.5 : 1,
                          }}
                          onClick={() => handleUnmount(detail.repo_id)}
                          disabled={unmounting.has(detail.repo_id)}
                        >
                          {unmounting.has(detail.repo_id) ? '...' : 'Unmount'}
                        </button>
                      </div>
                    ))}
                  </div>
                </div>
              )}

              {status.mounted_repos.length === 0 && (
                <div style={s.empty}>No repos mounted</div>
              )}

              {/* Errors collapsible */}
              {status.errors.length > 0 && (
                <div style={s.section}>
                  <button style={s.errToggle} onClick={() => setErrorsOpen(v => !v)}>
                    <span style={{ color: '#e05252' }}>
                      {status.errors.length} error{status.errors.length !== 1 ? 's' : ''}
                    </span>
                    <span style={s.chevron}>{errorsOpen ? '▲' : '▼'}</span>
                  </button>
                  {errorsOpen && (
                    <div style={s.errorList}>
                      {status.errors.slice(-10).map((err, i) => (
                        <div key={i} style={s.errorItem}>{err}</div>
                      ))}
                    </div>
                  )}
                </div>
              )}
            </>
          )}

          {!status && !statusError && (
            <div style={s.loading}>Loading...</div>
          )}
        </div>
      )}
    </div>
  )
}

const s: Record<string, React.CSSProperties> = {
  container: {
    borderBottom: '1px solid #333',
  },
  header: {
    width: '100%',
    display: 'flex',
    alignItems: 'center',
    justifyContent: 'space-between',
    padding: '10px 12px',
    background: 'transparent',
    border: 'none',
    color: '#e0e0e0',
    cursor: 'pointer',
    textAlign: 'left',
  },
  headerTitle: {
    fontSize: '11px',
    fontWeight: 600,
    textTransform: 'uppercase' as const,
    letterSpacing: '0.08em',
    color: '#888',
  },
  headerMeta: {
    display: 'flex',
    alignItems: 'center',
    gap: 4,
  },
  chevron: {
    fontSize: 10,
    color: '#555',
  },
  body: {
    padding: '0 12px 12px',
    display: 'flex',
    flexDirection: 'column' as const,
    gap: 8,
  },
  statsRow: {
    display: 'flex',
    gap: 12,
  },
  stat: {
    display: 'flex',
    flexDirection: 'column' as const,
    gap: 2,
  },
  statLabel: {
    fontSize: 10,
    color: '#666',
    textTransform: 'uppercase' as const,
    letterSpacing: '0.05em',
  },
  statValue: {
    fontSize: 12,
    color: '#c8e6c9',
    fontFamily: 'monospace',
  },
  scanBtn: {
    display: 'flex',
    alignItems: 'center',
    gap: 6,
    background: '#3a6ea5',
    border: 'none',
    borderRadius: 4,
    color: '#fff',
    padding: '6px 12px',
    fontSize: 12,
    cursor: 'pointer',
    alignSelf: 'flex-start' as const,
  },
  spinner: {
    display: 'inline-block',
    animation: 'spin 1s linear infinite',
    fontSize: 14,
  },
  scanResult: {
    fontSize: 12,
    padding: '4px 8px',
    background: '#1a1a1a',
    borderRadius: 4,
    border: '1px solid #2a2a2a',
  },
  section: {
    display: 'flex',
    flexDirection: 'column' as const,
    gap: 4,
  },
  sectionTitle: {
    fontSize: 10,
    fontWeight: 600,
    textTransform: 'uppercase' as const,
    letterSpacing: '0.06em',
    color: '#666',
    marginBottom: 2,
  },
  repoList: {
    display: 'flex',
    flexDirection: 'column' as const,
    gap: 4,
  },
  repoRow: {
    display: 'flex',
    alignItems: 'center',
    justifyContent: 'space-between',
    gap: 8,
    padding: '6px 8px',
    background: '#1a1a1a',
    borderRadius: 4,
    border: '1px solid #2a2a2a',
  },
  repoInfo: {
    display: 'flex',
    flexDirection: 'column' as const,
    gap: 2,
    minWidth: 0,
    flex: 1,
  },
  repoName: {
    fontSize: 12,
    color: '#c0d8f0',
    fontWeight: 500,
    overflow: 'hidden',
    textOverflow: 'ellipsis',
    whiteSpace: 'nowrap' as const,
  },
  repoMeta: {
    display: 'flex',
    alignItems: 'center',
    gap: 4,
    fontSize: 10,
    color: '#555',
  },
  repoMount: {
    fontFamily: 'monospace',
    overflow: 'hidden',
    textOverflow: 'ellipsis',
    whiteSpace: 'nowrap' as const,
    maxWidth: 120,
  },
  repoDot: {
    flexShrink: 0,
  },
  repoTime: {
    flexShrink: 0,
  },
  unmountBtn: {
    background: '#3a2020',
    border: '1px solid #5a2020',
    borderRadius: 3,
    color: '#e05252',
    padding: '3px 8px',
    fontSize: 11,
    cursor: 'pointer',
    flexShrink: 0,
  },
  empty: {
    fontSize: 12,
    color: '#555',
    padding: '4px 0',
  },
  errToggle: {
    display: 'flex',
    alignItems: 'center',
    justifyContent: 'space-between',
    width: '100%',
    background: 'transparent',
    border: 'none',
    cursor: 'pointer',
    padding: '4px 0',
    fontSize: 12,
  },
  errorList: {
    display: 'flex',
    flexDirection: 'column' as const,
    gap: 3,
  },
  errorItem: {
    fontSize: 11,
    color: '#e05252',
    fontFamily: 'monospace',
    padding: '3px 6px',
    background: '#1e1010',
    borderRadius: 3,
    wordBreak: 'break-all' as const,
  },
  error: {
    fontSize: 12,
    color: '#e05252',
  },
  loading: {
    fontSize: 12,
    color: '#666',
  },
}
