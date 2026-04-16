import type { ConverterTaskProgress } from '../types'

interface Props {
  tasks: ConverterTaskProgress[]
  summary: string
}

export function ConverterProgress({ tasks, summary }: Props) {
  if (tasks.length === 0) {
    return (
      <div className="converter-progress-empty">
        No conversion data available
      </div>
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

  return (
    <div className="converter-progress">
      <table className="converter-progress-table">
        <thead>
          <tr>
            <th>Cell/Task</th>
            <th>Total</th>
            <th>Done</th>
            <th>Pending</th>
            <th>Failed</th>
            <th>Progress</th>
          </tr>
        </thead>
        <tbody>
          {tasks.map(t => {
            const pct = t.total > 0 ? Math.round((t.done / t.total) * 100) : 0
            return (
              <tr key={t.cell_task}>
                <td className="mono">{t.cell_task}</td>
                <td>{t.total}</td>
                <td className="text-green">{t.done}</td>
                <td className="text-yellow">{t.pending}</td>
                <td className={t.failed > 0 ? 'text-red' : ''}>{t.failed}</td>
                <td>
                  <div className="converter-bar">
                    <div className="converter-bar-fill" style={{ width: `${pct}%` }} />
                  </div>
                </td>
              </tr>
            )
          })}
        </tbody>
        <tfoot>
          <tr>
            <td><strong>Total</strong></td>
            <td><strong>{totals.total}</strong></td>
            <td className="text-green"><strong>{totals.done}</strong></td>
            <td className="text-yellow"><strong>{totals.pending}</strong></td>
            <td className={totals.failed > 0 ? 'text-red' : ''}><strong>{totals.failed}</strong></td>
            <td>
              <div className="converter-bar">
                <div
                  className="converter-bar-fill"
                  style={{ width: `${totals.total > 0 ? Math.round((totals.done / totals.total) * 100) : 0}%` }}
                />
              </div>
            </td>
          </tr>
        </tfoot>
      </table>
      {summary && <div className="converter-summary">{summary}</div>}
    </div>
  )
}
