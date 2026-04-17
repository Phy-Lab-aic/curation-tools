import { useEffect, useMemo, useState, useRef, memo } from 'react'
import client from '../api/client'
import { useThemeVersion } from '../hooks/useThemeVersion'

interface ScalarData {
  episode_index: number
  num_frames: number
  observations: Record<string, number[]>
  actions: Record<string, number[]>
  terminal_frames?: number[]
  terminal_timestamps?: number[]
}

interface ScalarChartProps {
  episodeIndex: number | null
  currentFrame: number
  onTerminalFrames?: (frames: number[], timestamps: number[]) => void
}

const MiniChart = memo(function MiniChart({ label, series, color, currentFrame, collapsed, themeVersion }: {
  label: string
  series: number[]
  color: string
  currentFrame: number
  collapsed: boolean
  themeVersion: number
}) {
  const canvasRef = useRef<HTMLCanvasElement>(null)

  useEffect(() => {
    if (collapsed) return
    const canvas = canvasRef.current
    if (!canvas || series.length === 0) return

    const draw = () => {
      const ctx = canvas.getContext('2d')
      if (!ctx) return

      const dpr = window.devicePixelRatio || 1
      const w = canvas.clientWidth
      const h = canvas.clientHeight
      if (w === 0 || h === 0) return

      canvas.width = w * dpr
      canvas.height = h * dpr
      ctx.scale(dpr, dpr)

      const min = Math.min(...series)
      const max = Math.max(...series)
      const range = max - min || 1

      const cs = getComputedStyle(document.documentElement)
      const bg = cs.getPropertyValue('--bg-deep').trim()
      const gridColor = cs.getPropertyValue('--border').trim()
      const cursorColor = cs.getPropertyValue('--text').trim()

      // Background
      ctx.fillStyle = bg
      ctx.fillRect(0, 0, w, h)

      // Grid lines
      ctx.strokeStyle = gridColor
      ctx.lineWidth = 1
      for (let i = 0; i < 4; i++) {
        const y = (h / 4) * i
        ctx.beginPath()
        ctx.moveTo(0, y)
        ctx.lineTo(w, y)
        ctx.stroke()
      }

      // Data line
      ctx.strokeStyle = color
      ctx.lineWidth = 1.5
      ctx.beginPath()
      const denom = Math.max(series.length - 1, 1)
      for (let i = 0; i < series.length; i++) {
        const x = (i / denom) * w
        const y = h - ((series[i] - min) / range) * (h - 4) - 2
        if (i === 0) ctx.moveTo(x, y)
        else ctx.lineTo(x, y)
      }
      ctx.stroke()

      // Current frame indicator
      if (currentFrame >= 0 && currentFrame < series.length) {
        const x = (currentFrame / denom) * w
        ctx.strokeStyle = cursorColor
        ctx.lineWidth = 1
        ctx.setLineDash([2, 2])
        ctx.beginPath()
        ctx.moveTo(x, 0)
        ctx.lineTo(x, h)
        ctx.stroke()
        ctx.setLineDash([])

        const y = h - ((series[currentFrame] - min) / range) * (h - 4) - 2
        ctx.fillStyle = color
        ctx.beginPath()
        ctx.arc(x, y, 3, 0, Math.PI * 2)
        ctx.fill()
      }
    }

    draw()
    const ro = new ResizeObserver(draw)
    ro.observe(canvas)
    return () => ro.disconnect()
  }, [series, color, currentFrame, collapsed, themeVersion])

  const currentVal = currentFrame >= 0 && currentFrame < series.length
    ? series[currentFrame].toFixed(3)
    : '--'

  return (
    <div style={chartStyles.chartItem}>
      <div style={chartStyles.chartHeader}>
        <span style={{ ...chartStyles.chartLabel, color }}>{label}</span>
        <span style={chartStyles.chartValue}>{currentVal}</span>
      </div>
      {!collapsed && (
        <canvas
          ref={canvasRef}
          style={chartStyles.canvas}
        />
      )}
    </div>
  )
})

export function ScalarChart({ episodeIndex, currentFrame, onTerminalFrames }: ScalarChartProps) {
  const [data, setData] = useState<ScalarData | null>(null)
  const [loading, setLoading] = useState(false)
  const [error, setError] = useState<string | null>(null)
  const [obsCollapsed, setObsCollapsed] = useState(false)
  const [actCollapsed, setActCollapsed] = useState(false)
  const themeVersion = useThemeVersion()

  useEffect(() => {
    if (episodeIndex === null) {
      setData(null)
      setError(null)
      onTerminalFrames?.([], [])
      return
    }
    setLoading(true)
    setError(null)
    client.get<ScalarData>(`/scalars/${episodeIndex}`)
      .then(res => {
        setData(res.data)
        onTerminalFrames?.(res.data.terminal_frames ?? [], res.data.terminal_timestamps ?? [])
      })
      .catch(err => {
        setData(null)
        setError(err?.message || 'Failed to load scalar data')
        onTerminalFrames?.([], [])
      })
      .finally(() => setLoading(false))
  }, [episodeIndex]) // eslint-disable-line react-hooks/exhaustive-deps

  if (episodeIndex === null) return null

  if (loading) {
    return (
      <div style={chartStyles.container}>
        <div style={chartStyles.loading}>Loading scalar data...</div>
      </div>
    )
  }

  if (error) {
    return (
      <div style={chartStyles.container}>
        <div style={chartStyles.error}>Scalar data unavailable</div>
      </div>
    )
  }

  if (!data) return null

  const obsKeys = Object.keys(data.observations)
  const actKeys = Object.keys(data.actions)

  if (obsKeys.length === 0 && actKeys.length === 0) return null

  return (
    <div style={chartStyles.container}>
      <div style={chartStyles.columns}>
        {obsKeys.length > 0 && (
          <div style={chartStyles.column}>
            <div
              role="button"
              tabIndex={0}
              style={chartStyles.sectionHeader}
              onClick={() => setObsCollapsed(!obsCollapsed)}
              onKeyDown={(e) => {
                if (e.key === 'Enter' || e.key === ' ') {
                  e.preventDefault()
                  setObsCollapsed(!obsCollapsed)
                }
              }}
            >
              <span style={chartStyles.sectionTitle}>
                {obsCollapsed ? '\u25B6' : '\u25BC'} Observation.state
              </span>
              <span style={chartStyles.sectionCount}>{obsKeys.length}</span>
            </div>
            {obsKeys.map(key => (
              <MiniChart
                key={key}
                label={key.replace('observation.', '').replace('state.', '')}
                series={data.observations[key]}
                color="var(--c-blue)"
                currentFrame={currentFrame}
                collapsed={obsCollapsed}
                themeVersion={themeVersion}
              />
            ))}
          </div>
        )}

        {actKeys.length > 0 && (
          <div style={chartStyles.column}>
            <div
              role="button"
              tabIndex={0}
              style={chartStyles.sectionHeader}
              onClick={() => setActCollapsed(!actCollapsed)}
              onKeyDown={(e) => {
                if (e.key === 'Enter' || e.key === ' ') {
                  e.preventDefault()
                  setActCollapsed(!actCollapsed)
                }
              }}
            >
              <span style={chartStyles.sectionTitle}>
                {actCollapsed ? '\u25B6' : '\u25BC'} Action
              </span>
              <span style={chartStyles.sectionCount}>{actKeys.length}</span>
            </div>
            {actKeys.map(key => (
              <MiniChart
                key={key}
                label={key.replace('action.', '')}
                series={data.actions[key]}
                color="var(--accent)"
                currentFrame={currentFrame}
                collapsed={actCollapsed}
                themeVersion={themeVersion}
              />
            ))}
          </div>
        )}
      </div>
    </div>
  )
}

const chartStyles: Record<string, React.CSSProperties> = {
  container: { display: 'flex', flexDirection: 'column', overflow: 'hidden', flexShrink: 1 },
  loading: { padding: '12px', fontSize: '12px', color: 'var(--text-muted)' as string },
  error: { padding: '12px', fontSize: '12px', color: 'var(--c-red)' as string },
  columns: { display: 'grid', gridTemplateColumns: '1fr 1fr', gap: 0, borderBottom: '1px solid var(--border)' as string },
  column: { display: 'flex', flexDirection: 'column', minWidth: 0, borderRight: '1px solid var(--border)' as string },
  sectionHeader: {
    display: 'flex', justifyContent: 'space-between', alignItems: 'center',
    padding: '6px 10px', cursor: 'pointer',
    background: 'var(--panel)' as string,
    borderBottom: '1px solid var(--border2)' as string,
  },
  sectionTitle: { fontSize: '11px', fontWeight: 600, textTransform: 'uppercase' as const, letterSpacing: '0.06em', color: 'var(--text-muted)' as string, overflow: 'hidden', textOverflow: 'ellipsis', whiteSpace: 'nowrap' as const },
  sectionCount: { fontSize: '11px', color: 'var(--text-dim)' as string, fontFamily: 'var(--font-mono)' },
  chartItem: { padding: '3px 10px', borderBottom: '1px solid var(--border)', minWidth: 0 },
  chartHeader: { display: 'flex', justifyContent: 'space-between', alignItems: 'center', marginBottom: '2px', gap: '6px' },
  chartLabel: { fontSize: '11px', fontFamily: 'var(--font-mono)', fontWeight: 500, overflow: 'hidden', textOverflow: 'ellipsis', whiteSpace: 'nowrap' as const, minWidth: 0 },
  chartValue: { fontSize: '11px', fontFamily: 'var(--font-mono)', color: 'var(--text-muted)' as string, flexShrink: 0 },
  canvas: { width: '100%', height: '40px', borderRadius: '2px' },
}
