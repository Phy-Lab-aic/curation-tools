import { useEffect, useState } from 'react'
import { ConverterControls } from './ConverterControls'
import { ConverterProgress } from './ConverterProgress'
import { ConverterLogs } from './ConverterLogs'
import type { ConverterStatus } from '../types'

interface Props {
  status: ConverterStatus
  onRefresh: () => void
}

export function ConverterPage({ status, onRefresh }: Props) {
  const [logsOpen, setLogsOpen] = useState(false)

  useEffect(() => {
    if (status.container_state !== 'running') return
    const id = setInterval(onRefresh, 10000)
    return () => clearInterval(id)
  }, [status.container_state, onRefresh])

  return (
    <div className="converter-page">
      <ConverterControls
        containerState={status.container_state}
        dockerAvailable={status.docker_available}
        onRefresh={onRefresh}
      />
      <div className="converter-body">
        <ConverterProgress
          tasks={status.tasks}
          containerState={status.container_state}
          dockerAvailable={status.docker_available}
          onRefresh={onRefresh}
        />
      </div>
      <ConverterLogs
        containerState={status.container_state}
        open={logsOpen}
        onToggle={() => setLogsOpen(v => !v)}
      />
    </div>
  )
}
