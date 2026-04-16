import { useCallback, useEffect, useState } from 'react'
import { ConverterControls } from './ConverterControls'
import { ConverterProgress } from './ConverterProgress'
import { ConverterLogs } from './ConverterLogs'
import type { ConverterStatus } from '../types'

const API = '/api/converter'

export function ConverterPage() {
  const [status, setStatus] = useState<ConverterStatus>({
    container_state: 'unknown',
    docker_available: false,
    tasks: [],
    summary: '',
  })

  const fetchStatus = useCallback(async () => {
    try {
      const res = await fetch(`${API}/status`)
      if (res.ok) {
        setStatus(await res.json())
      }
    } catch {
      // ignore fetch errors
    }
  }, [])

  // Poll status every 5 seconds
  useEffect(() => {
    fetchStatus()
    const id = setInterval(fetchStatus, 5000)
    return () => clearInterval(id)
  }, [fetchStatus])

  // Poll progress every 10 seconds when running
  useEffect(() => {
    if (status.container_state !== 'running') return

    const id = setInterval(async () => {
      try {
        const res = await fetch(`${API}/progress`)
        if (res.ok) {
          const data = await res.json()
          setStatus(prev => ({ ...prev, tasks: data.tasks, summary: data.summary }))
        }
      } catch {
        // ignore
      }
    }, 10000)

    return () => clearInterval(id)
  }, [status.container_state])

  return (
    <div className="converter-page">
      <ConverterControls
        containerState={status.container_state}
        dockerAvailable={status.docker_available}
        onRefresh={fetchStatus}
      />
      <ConverterProgress tasks={status.tasks} summary={status.summary} />
      <ConverterLogs containerState={status.container_state} />
    </div>
  )
}
