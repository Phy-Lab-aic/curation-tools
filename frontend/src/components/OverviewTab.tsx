import { useEffect, useState } from 'react'
import { BarChart, Bar, XAxis, YAxis, Tooltip, ResponsiveContainer } from 'recharts'
import { useDistribution } from '../hooks/useDistribution'
import type { DistributionResult } from '../types'

interface OverviewTabProps {
  datasetPath: string
}

const CHART_COLORS = ['#5794f2', '#73bf69', '#fade2a', '#f08080', '#b877d9', '#ff9830']

export function OverviewTab({ datasetPath }: OverviewTabProps) {
  const { fields, charts, loading, error, fetchFields, addChart, removeChart } = useDistribution()
  const [selectedFields, setSelectedFields] = useState<Set<string>>(new Set())

  useEffect(() => {
    void fetchFields(datasetPath)
  }, [datasetPath, fetchFields])

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

  const systemFields = fields.filter(f => f.is_system)
  const customFields = fields.filter(f => !f.is_system)

  return (
    <div className="overview-layout">
      <div className="overview-fields-panel">
        <FieldSection title="System columns" fields={systemFields} selected={selectedFields} onToggle={toggleField} />
        <FieldSection title="Custom columns" fields={customFields} selected={selectedFields} onToggle={toggleField} />
      </div>

      <div className="overview-charts">
        <div className="stats-bar">
          <div className="stat-card">
            <div className="stat-card-n">{charts.length > 0 ? charts[0].total : '—'}</div>
            <div className="stat-card-l">Episodes</div>
          </div>
          <div className="stat-card">
            <div className="stat-card-n">{charts.length}</div>
            <div className="stat-card-l">Charts</div>
          </div>
          <div className="stat-card">
            <div className="stat-card-n">{fields.length}</div>
            <div className="stat-card-l">Fields</div>
          </div>
        </div>

        {loading && <div style={{ fontSize: 11, color: 'var(--text-muted)' }}>Computing...</div>}
        {error && <div style={{ fontSize: 11, color: 'var(--c-red)' }}>{error}</div>}

        {charts.map((chart, idx) => (
          <ChartPanel
            key={chart.field}
            chart={chart}
            color={CHART_COLORS[idx % CHART_COLORS.length]}
            onRemove={() => {
              removeChart(chart.field)
              setSelectedFields(prev => {
                const next = new Set(prev)
                next.delete(chart.field)
                return next
              })
            }}
            onChangeType={(newType) => void addChart(datasetPath, chart.field, newType)}
          />
        ))}

        {charts.length === 0 && !loading && (
          <div style={{ padding: 20, textAlign: 'center', color: 'var(--text-muted)', fontSize: 12 }}>
            Select fields from the left panel to visualize distributions
          </div>
        )}
      </div>
    </div>
  )
}

function FieldSection({
  title, fields, selected, onToggle,
}: {
  title: string
  fields: { name: string; dtype: string }[]
  selected: Set<string>
  onToggle: (name: string) => void
}) {
  if (fields.length === 0) return null
  return (
    <div className="fields-panel-section">
      <div className="fields-panel-section-header">
        <span>{title}</span>
        <span style={{ color: 'var(--text-dim)', fontSize: 9 }}>{fields.length}</span>
      </div>
      {fields.map(f => (
        <label key={f.name} className={`field-checkbox${selected.has(f.name) ? ' checked' : ''}`}>
          <input type="checkbox" checked={selected.has(f.name)} onChange={() => onToggle(f.name)} />
          <span>{f.name}</span>
          <span style={{ marginLeft: 'auto', fontSize: 9, color: 'var(--text-dim)' }}>{f.dtype}</span>
        </label>
      ))}
    </div>
  )
}

function ChartPanel({
  chart, color, onRemove, onChangeType,
}: {
  chart: DistributionResult
  color: string
  onRemove: () => void
  onChangeType: (type: string) => void
}) {
  return (
    <div className="chart-panel">
      <div className="chart-panel-header">
        <span className="chart-panel-title">{chart.field}</span>
        <div style={{ display: 'flex', gap: 6, alignItems: 'center' }}>
          <select
            className="chart-type-select"
            value={chart.chart_type}
            onChange={e => onChangeType(e.target.value)}
          >
            <option value="histogram">Histogram</option>
            <option value="bar">Bar</option>
          </select>
          <span style={{ fontSize: 9, color: 'var(--text-dim)' }}>n={chart.total}</span>
          <button className="chart-panel-close" onClick={onRemove}>×</button>
        </div>
      </div>
      <div className="chart-panel-body">
        <ResponsiveContainer width="100%" height="100%">
          <BarChart data={chart.bins} margin={{ top: 4, right: 4, bottom: 0, left: 0 }}>
            <XAxis
              dataKey="label"
              tick={{ fontSize: 9, fill: '#555' }}
              axisLine={{ stroke: '#222' }}
              tickLine={false}
            />
            <YAxis
              tick={{ fontSize: 9, fill: '#555' }}
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
            <Bar dataKey="count" fill={color} radius={[2, 2, 0, 0]} />
          </BarChart>
        </ResponsiveContainer>
      </div>
    </div>
  )
}
