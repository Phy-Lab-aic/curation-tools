import { useState } from 'react'
import type { ConverterState, ConverterTaskProgress } from '../types'

interface Props {
  tasks: ConverterTaskProgress[]
  containerState: ConverterState
  dockerAvailable: boolean
  onRefresh: () => void
}

const API = '/api/converter'

function taskLabel(cell_task: string) {
  const parts = cell_task.split('/')
  return parts[parts.length - 1] || cell_task
}

function taskCell(cell_task: string) {
  const parts = cell_task.split('/')
  return parts[0] || ''
}

export function ConverterProgress({ tasks, containerState, dockerAvailable, onRefresh }: Props) {
  const [starting, setStarting] = useState<string | null>(null)

  const startTask = async (cell_task: string) => {
    setStarting(cell_task)
    try {
      const res = await fetch(`${API}/start`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ cell_task }),
      })
      if (!res.ok) {
        const body = await res.json().catch(() => ({}))
        console.error('start(task) failed:', body)
      }
      onRefresh()
    } finally {
      setStarting(null)
    }
  }

  if (tasks.length === 0) {
    return (
      <div className="cvp-empty">No conversion data</div>
    )
  }

  const totals = tasks.reduce(
    (acc, t) => ({
      total: acc.total + t.total,
      done: acc.done + t.done,
      pending: acc.pending + t.pending,
      failed: acc.failed + t.failed,
    }),
    { total: 0, done: 0, pending: 0, failed: 0 },
  )

  const overallPct = totals.total > 0 ? Math.round((totals.done / totals.total) * 100) : 0
  const canStart = dockerAvailable
    && containerState !== 'running'
    && containerState !== 'building'
    && starting === null

  return (
    <div className="cvp-root">
      {/* Hero */}
      <div className="cvp-hero">
        <div className="cvp-hero-left">
          <span className="cvp-pct">{overallPct}</span>
          <span className="cvp-pct-unit">%</span>
        </div>
        <div className="cvp-hero-right">
          <div className="cvp-bar-wide">
            <div className="cvp-bar-fill" style={{ width: `${overallPct}%` }} />
          </div>
          <div className="cvp-pills">
            <span className="cvp-pill cvp-pill-green">
              <span className="cvp-pill-num" style={{ fontFamily: 'var(--font-mono)' }}>{totals.done}</span>
              <span className="cvp-pill-label">done</span>
            </span>
            <span className="cvp-pill cvp-pill-yellow">
              <span className="cvp-pill-num" style={{ fontFamily: 'var(--font-mono)' }}>{totals.pending}</span>
              <span className="cvp-pill-label">pending</span>
            </span>
            {totals.failed > 0 && (
              <span className="cvp-pill cvp-pill-red">
                <span className="cvp-pill-num" style={{ fontFamily: 'var(--font-mono)' }}>{totals.failed}</span>
                <span className="cvp-pill-label">failed</span>
              </span>
            )}
          </div>
        </div>
      </div>

      {/* Task cards */}
      <div className="cvp-cards">
        {tasks.map(t => {
          const pct = t.total > 0 ? Math.round((t.done / t.total) * 100) : 0
          const hasPending = t.pending > 0
          const disabled = !canStart || !hasPending
          const isStartingThis = starting === t.cell_task
          return (
            <div key={t.cell_task} className="cvp-card">
              <div className="cvp-card-header">
                <span className="cvp-card-cell">{taskCell(t.cell_task)}</span>
                <span className="cvp-card-name">{taskLabel(t.cell_task)}</span>
                <span className="cvp-card-fraction" style={{ fontFamily: 'var(--font-mono)' }}>
                  {t.done}/{t.total}
                </span>
              </div>
              <div className="cvp-card-bar">
                <div className="cvp-card-bar-fill" style={{ width: `${pct}%` }} />
              </div>
              <div className="cvp-card-footer">
                {t.failed > 0 ? (
                  <div className="cvp-card-failed">{t.failed} failed</div>
                ) : (
                  <div />
                )}
                <button
                  type="button"
                  className="btn-secondary cvp-card-convert"
                  disabled={disabled}
                  onClick={() => startTask(t.cell_task)}
                >
                  {isStartingThis ? 'Starting...' : 'Convert'}
                </button>
              </div>
            </div>
          )
        })}
      </div>
    </div>
  )
}
