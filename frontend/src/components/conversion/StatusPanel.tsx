// frontend/src/components/conversion/StatusPanel.tsx
import React from 'react'
import type { ConversionJob, WatchStatus } from '../../hooks/useConversion'

interface Props {
  watchStatus: WatchStatus
  jobs: ConversionJob[]
  selectedProfile: string | null
  onStartWatch: () => void
  onStopWatch: () => void
  onRunOnce: () => void
}

export function StatusPanel({ watchStatus, jobs, selectedProfile, onStartWatch, onStopWatch, onRunOnce }: Props) {
  const activeJobs = jobs.filter(j => j.status === 'queued' || j.status === 'converting')
  const historyJobs = jobs.filter(j => j.status === 'done' || j.status === 'failed')

  return (
    <div className="conversion-status-panel">
      {/* Watch toggle */}
      <div className="conversion-watch-card">
        <div className="conversion-watch-info">
          <div className="conversion-watch-title">Auto Watch Mode</div>
          <div className="conversion-watch-sub">새 MCAP 감지 → 변환 → processed/ 이동</div>
        </div>
        <div className="conversion-watch-toggle">
          <button
            className={`toggle-btn ${watchStatus.watching ? 'active' : ''}`}
            onClick={watchStatus.watching ? onStopWatch : onStartWatch}
            disabled={!selectedProfile && !watchStatus.watching}
          >
            <span className="toggle-knob" />
          </button>
          <span className={`toggle-label ${watchStatus.watching ? 'active' : ''}`}>
            {watchStatus.watching ? 'Watching' : 'Stopped'}
          </span>
        </div>
      </div>

      {/* Manual controls */}
      <div className="conversion-controls">
        <button
          className="btn-secondary conversion-run-btn"
          onClick={onRunOnce}
          disabled={!selectedProfile}
        >
          ▶ Run Once
        </button>
        {watchStatus.watching && (
          <button className="btn-danger-outline" onClick={onStopWatch}>■ Stop</button>
        )}
      </div>

      {/* Active jobs */}
      {activeJobs.length > 0 && (
        <div className="conversion-jobs-section">
          <div className="conversion-jobs-title">Active Jobs</div>
          <div className="conversion-jobs-list">
            {activeJobs.map(job => (
              <div key={job.id} className="conversion-job-item">
                <div className="conversion-job-header">
                  <span className="conversion-job-folder">{job.folder}/</span>
                  <span className={`conversion-job-badge ${job.status}`}>
                    {job.status === 'converting' ? 'Converting' : 'Queued'}
                  </span>
                </div>
                {job.status === 'converting' && (
                  <>
                    <div className="conversion-progress-bar">
                      <div className="conversion-progress-fill indeterminate" />
                    </div>
                    <div className="conversion-job-message">{job.message}</div>
                  </>
                )}
              </div>
            ))}
          </div>
        </div>
      )}

      {/* History */}
      {historyJobs.length > 0 && (
        <div className="conversion-jobs-section">
          <div className="conversion-jobs-title">Recent History</div>
          <div className="conversion-jobs-list">
            {historyJobs.slice(-20).reverse().map(job => (
              <div key={job.id} className="conversion-job-item history">
                <span className="conversion-job-folder">{job.folder}/</span>
                <div className="conversion-job-outcome">
                  {job.status === 'done' ? (
                    <>
                      <span className="conversion-job-dest">{job.message}</span>
                      <span className="conversion-job-badge done">✓ Done</span>
                    </>
                  ) : (
                    <span className="conversion-job-badge failed" title={job.message}>✗ Failed</span>
                  )}
                </div>
              </div>
            ))}
          </div>
        </div>
      )}

      {activeJobs.length === 0 && historyJobs.length === 0 && (
        <div className="conversion-empty">No jobs yet. Start watching or run once.</div>
      )}
    </div>
  )
}
