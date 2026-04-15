import { useEffect, useMemo, useRef, useState } from 'react'
import { BarChart, Bar, XAxis, YAxis, Tooltip, ResponsiveContainer } from 'recharts'
import { useDistribution } from '../hooks/useDistribution'
import type { CurateFilter, DistributionResult, Episode } from '../types'

interface OverviewTabProps {
  datasetPath: string
  fps: number
  episodes: Episode[]
  onNavigateCurate: (filter: CurateFilter) => void
}

const CHART_COLORS = ['#89b4fa', '#a6e3a1', '#f9e2af', '#f38ba8', '#cba6f7', '#ff9830']
const AUTO_FIELDS = new Set(['grade', 'tags', 'length', 'task_instruction', 'collection_date'])

const FIELD_LABELS: Record<string, string> = {
  grade: 'Grade',
  tags: 'Tags',
  length: 'Episode Length',
  task_instruction: 'Task Instruction',
  collection_date: 'Collection Date',
}

export function OverviewTab({ datasetPath, fps, episodes, onNavigateCurate }: OverviewTabProps) {
  const { fields, charts, loading, error, fetchFields, addChart, removeChart } = useDistribution()
  const [selectedFields, setSelectedFields] = useState<Set<string>>(new Set())
  const [chartIntensity, setChartIntensity] = useState(1)
  const initializedRef = useRef(false)

  useEffect(() => {
    initializedRef.current = false
    setSelectedFields(new Set())
  }, [datasetPath])

  useEffect(() => {
    void fetchFields(datasetPath)
  }, [datasetPath, fetchFields])

  useEffect(() => {
    if (fields.length > 0 && !initializedRef.current) {
      initializedRef.current = true
      const autoFields = fields.filter(f => AUTO_FIELDS.has(f.name))
      if (autoFields.length > 0) {
        const names = new Set(autoFields.map(f => f.name))
        setSelectedFields(names)
        autoFields.forEach(f => {
          void addChart(datasetPath, f.name, f.name === 'length' ? 'histogram' : 'auto')
        })
      }
    }
  }, [fields, datasetPath, addChart])

  const toggleField = (fieldName: string) => {
    setSelectedFields(prev => {
      const next = new Set(prev)
      if (next.has(fieldName)) {
        next.delete(fieldName)
        removeChart(fieldName)
      } else {
        next.add(fieldName)
        void addChart(datasetPath, fieldName)
      }
      return next
    })
  }

  const gradeChart = charts.find(c => c.field === 'grade')
  const otherCharts = charts.filter(c => c.field !== 'grade')

  return (
    <div className="overview-layout">
      <div className="overview-fields-panel">
        <div className="fields-panel-section">
          <div className="fields-panel-section-header">
            <span>Fields</span>
            <span style={{ color: 'var(--text-dim)', fontSize: 9 }}>{fields.length}</span>
          </div>
          {fields.map(f => (
            <label key={f.name} className={`field-checkbox${selectedFields.has(f.name) ? ' checked' : ''}`}>
              <input type="checkbox" checked={selectedFields.has(f.name)} onChange={() => toggleField(f.name)} />
              <span>{FIELD_LABELS[f.name] ?? f.name}</span>
            </label>
          ))}
        </div>
        <div className="fields-panel-section">
          <div className="fields-panel-section-header">
            <span>Chart Intensity</span>
          </div>
          <div style={{ padding: '6px 12px 10px' }}>
            <input
              type="range"
              min={0.1}
              max={2}
              step={0.05}
              value={chartIntensity}
              onChange={e => setChartIntensity(Number(e.target.value))}
              style={{ width: '100%', accentColor: 'var(--accent)' }}
            />
          </div>
        </div>
      </div>

      <div className="overview-charts">
        {gradeChart && <GradeSummary chart={gradeChart} fps={fps} episodes={episodes} onNavigateCurate={onNavigateCurate} />}

        {loading && <div className="loading-pulse" style={{ fontSize: 11, color: 'var(--text-muted)' }}>Computing...</div>}
        {error && <div style={{ fontSize: 11, color: 'var(--c-red)' }}>{error}</div>}

        {otherCharts.map((chart, idx) => {
          let onBarClick: ((label: string) => void) | undefined
          if (chart.field === 'length') {
            onBarClick = (label: string) => {
              const parts = label.split('-').map(Number)
              if (parts.length === 2 && parts.every(n => !isNaN(n))) {
                onNavigateCurate({ lengthRange: [parts[0], parts[1]] })
              }
            }
          } else if (chart.field === 'tags') {
            onBarClick = (label: string) => {
              if (label !== '(no tags)') onNavigateCurate({ tag: label })
            }
          }
          return (
            <ChartPanel
              key={chart.field}
              chart={chart}
              color={CHART_COLORS[idx % CHART_COLORS.length]}
              fps={chart.field === 'length' ? fps : undefined}
              onBarClick={onBarClick}
              intensity={chartIntensity}
            />
          )
        })}

        {charts.length === 0 && !loading && (
          <div style={{ padding: 20, textAlign: 'center', color: 'var(--text-muted)', fontSize: 12 }}>
            Select fields from the left panel
          </div>
        )}
      </div>
    </div>
  )
}

/* ── Grade summary ────────────────────────────── */

function formatDuration(totalSeconds: number): string {
  const hours = Math.floor(totalSeconds / 3600)
  const minutes = Math.floor((totalSeconds % 3600) / 60)
  const secs = Math.floor(totalSeconds % 60)
  if (hours > 0) return `${hours}h ${minutes}m ${secs}s`
  if (minutes > 0) return `${minutes}m ${secs}s`
  return `${secs}s`
}

function formatCompactDuration(totalSeconds: number): string {
  const hours = Math.floor(totalSeconds / 3600)
  const minutes = Math.floor((totalSeconds % 3600) / 60)
  const secs = Math.floor(totalSeconds % 60)
  if (hours > 0) return `${hours}h${minutes}m`
  if (minutes > 0) return `${minutes}m${secs}s`
  return `${secs}s`
}

function GradeSummary({ chart, fps, episodes, onNavigateCurate }: {
  chart: DistributionResult
  fps: number
  episodes: Episode[]
  onNavigateCurate: (filter: CurateFilter) => void
}) {
  const total = chart.total
  const gradeMap: Record<string, number> = {}
  for (const bin of chart.bins) {
    gradeMap[bin.label] = bin.count
  }

  // Calculate per-grade duration from actual episodes
  const gradeDurations = useMemo(() => {
    const durations: Record<string, number> = { good: 0, normal: 0, bad: 0, '(ungraded)': 0, total: 0 }
    for (const ep of episodes) {
      const seconds = fps > 0 ? ep.length / fps : 0
      const key = ep.grade && ep.grade in durations ? ep.grade : '(ungraded)'
      durations[key] += seconds
      durations.total += seconds
    }
    return durations
  }, [episodes, fps])

  const items = [
    { label: 'Good', key: 'good', color: 'var(--c-green)', bg: 'rgba(166, 227, 161, 0.08)' },
    { label: 'Normal', key: 'normal', color: 'var(--c-yellow)', bg: 'rgba(249, 226, 175, 0.08)' },
    { label: 'Bad', key: 'bad', color: 'var(--c-red)', bg: 'rgba(243, 139, 168, 0.08)' },
    { label: 'Ungraded', key: '(ungraded)', color: 'var(--text-dim)', bg: 'rgba(85, 85, 85, 0.08)' },
  ]

  return (
    <div style={{ background: 'var(--panel)', border: '1px solid var(--border)', borderRadius: 8 }}>
      <div style={{ fontSize: 10, color: 'var(--text-dim)', textTransform: 'uppercase', letterSpacing: '0.06em', padding: '12px 14px 6px' }}>
        Grade Summary
      </div>
      <div style={{ display: 'grid', gridTemplateColumns: 'repeat(4, 1fr)', gap: 8, padding: '0 14px 10px' }}>
        {items.map(item => {
          const count = gradeMap[item.key] ?? 0
          const pct = total > 0 ? Math.round((count / total) * 100) : 0
          const dur = gradeDurations[item.key] ?? 0
          return (
            <div key={item.key} style={{
              background: item.bg,
              border: `1px solid ${count > 0 ? item.color : 'var(--border)'}`,
              borderRadius: 8,
              padding: '12px 10px',
              textAlign: 'center',
              cursor: 'pointer',
              transition: 'transform 0.15s, border-color 0.15s',
            }}
              onClick={() => onNavigateCurate({ grade: item.key === '(ungraded)' ? 'ungraded' : item.key })}
              onMouseEnter={e => {
                (e.currentTarget as HTMLElement).style.transform = 'scale(1.02)'
                ;(e.currentTarget as HTMLElement).style.borderColor = item.color
              }}
              onMouseLeave={e => {
                (e.currentTarget as HTMLElement).style.transform = 'scale(1)'
                ;(e.currentTarget as HTMLElement).style.borderColor = count > 0 ? item.color : 'var(--border)'
              }}
            >
              <div style={{ fontSize: 24, fontWeight: 700, color: item.color, lineHeight: 1, fontVariantNumeric: 'tabular-nums' }}>
                {count}
              </div>
              <div style={{ fontSize: 10, color: item.color, marginTop: 4, fontWeight: 600 }}>
                {item.label}
              </div>
              <div style={{ fontSize: 9, color: 'var(--text-dim)', marginTop: 2 }}>
                {pct}%
              </div>
              <div style={{ fontSize: 10, color: 'var(--text-muted)', marginTop: 6, borderTop: '1px solid var(--border)', paddingTop: 6 }}>
                <span style={{ fontWeight: 600, color: item.color }}>{formatDuration(dur)}</span>
              </div>
            </div>
          )
        })}
      </div>
      <div style={{ display: 'flex', height: 4, margin: '0 14px 12px', borderRadius: 2, overflow: 'hidden', gap: 1 }}>
        {items.map(item => {
          const count = gradeMap[item.key] ?? 0
          const pct = total > 0 ? (count / total) * 100 : 0
          if (pct === 0) return null
          return <div key={item.key} style={{ width: `${pct}%`, background: item.color, borderRadius: 1 }} />
        })}
      </div>
      {/* Total summary */}
      <div style={{ display: 'flex', justifyContent: 'flex-end', padding: '0 14px 12px', fontSize: 12, color: 'var(--text-muted)' }}>
        <span>Total: <strong style={{ color: 'var(--text)' }}>{formatDuration(gradeDurations.total)}</strong></span>
      </div>
    </div>
  )
}

/* ── Wrapped axis tick ────────────────────────── */

function WrappedTick({ x, y, payload, formatter }: {
  x?: number; y?: number; payload?: { value: string }
  formatter?: (label: string) => string
}) {
  if (!payload) return null
  const label = formatter ? formatter(payload.value) : payload.value
  const MAX_CHARS = 10
  if (label.length <= MAX_CHARS) {
    return (
      <text x={x} y={y} dy={12} textAnchor="middle" fontSize={11} fill="#999">
        {label}
      </text>
    )
  }
  // Split near the middle at a word boundary or hyphen
  const mid = Math.ceil(label.length / 2)
  let splitIdx = label.lastIndexOf(' ', mid)
  if (splitIdx <= 0) splitIdx = label.lastIndexOf('-', mid)
  if (splitIdx <= 0) splitIdx = mid
  const line1 = label.slice(0, splitIdx).trim()
  const line2 = label.slice(splitIdx).replace(/^[-\s]/, '').trim()
  return (
    <text x={x} y={y} textAnchor="middle" fontSize={10} fill="#999">
      <tspan x={x} dy={10}>{line1}</tspan>
      <tspan x={x} dy={13}>{line2}</tspan>
    </text>
  )
}

/* ── Chart panel ──────────────────────────────── */

function ChartPanel({ chart, color, fps, onBarClick, intensity = 1 }: {
  chart: DistributionResult
  color: string
  fps?: number
  onBarClick?: (label: string) => void
  intensity?: number
}) {
  const gradientId = `gradient-${chart.field}`

  const formatLabel = (label: string) => {
    if (!fps || chart.field !== 'length') return label
    const parts = label.split('-').map(Number)
    if (parts.length !== 2 || parts.some(isNaN)) return label
    return `${formatCompactDuration(parts[0] / fps)}-${formatCompactDuration(parts[1] / fps)}`
  }

  return (
    <div className="chart-panel">
      <div className="chart-panel-header">
        <span className="chart-panel-title">{FIELD_LABELS[chart.field] ?? chart.field}</span>
        <span style={{ fontSize: 9, color: 'var(--text-dim)' }}>{chart.total}</span>
      </div>
      <div className="chart-panel-body">
        <ResponsiveContainer width="100%" height="100%">
          <BarChart data={chart.bins} margin={{ top: 4, right: 4, bottom: 0, left: 0 }}>
            <defs>
              <linearGradient id={gradientId} x1="0" y1="1" x2="0" y2="0">
                <stop offset="0%" stopColor={color} stopOpacity={intensity * 0.5} />
                <stop offset="100%" stopColor={color} stopOpacity={intensity * 0.16} />
              </linearGradient>
            </defs>
            <XAxis
              dataKey="label"
              tick={<WrappedTick formatter={formatLabel} />}
              axisLine={{ stroke: '#222' }}
              tickLine={false}
              height={40}
            />
            <YAxis
              tick={{ fontSize: 11, fill: '#999' }}
              axisLine={false}
              tickLine={false}
              width={30}
            />
            <Tooltip
              contentStyle={{
                background: '#161616',
                border: '1px solid #2a2a2a',
                borderRadius: 4,
                fontSize: 11,
                color: '#d9d9d9',
              }}
            />
            <Bar
              dataKey="count"
              fill={`url(#${gradientId})`}
              stroke={color}
              strokeOpacity={intensity * 0.8}
              radius={[2, 2, 0, 0]}
              cursor={onBarClick ? 'pointer' : undefined}
              onClick={onBarClick ? (data: { label?: string }) => {
                if (data.label) onBarClick(data.label)
              } : undefined}
              activeBar={onBarClick ? { strokeOpacity: 0.8 } : undefined}
            />
          </BarChart>
        </ResponsiveContainer>
      </div>
    </div>
  )
}
