import { useEffect, useRef, useState } from 'react'

interface Props {
  containerState: string
}

const MAX_LINES = 500

export function ConverterLogs({ containerState }: Props) {
  const [lines, setLines] = useState<string[]>([])
  const [autoScroll, setAutoScroll] = useState(true)
  const bottomRef = useRef<HTMLDivElement>(null)
  const containerRef = useRef<HTMLDivElement>(null)

  useEffect(() => {
    if (containerState !== 'running') return

    const proto = window.location.protocol === 'https:' ? 'wss:' : 'ws:'
    const ws = new WebSocket(`${proto}//${window.location.host}/api/converter/logs`)

    ws.onmessage = (evt) => {
      setLines(prev => {
        const next = [...prev, evt.data]
        return next.length > MAX_LINES ? next.slice(-MAX_LINES) : next
      })
    }

    ws.onclose = () => {
      setLines(prev => [...prev, '[connection closed]'])
    }

    return () => {
      ws.close()
    }
  }, [containerState])

  useEffect(() => {
    if (autoScroll) {
      bottomRef.current?.scrollIntoView({ behavior: 'smooth' })
    }
  }, [lines, autoScroll])

  const handleScroll = () => {
    const el = containerRef.current
    if (!el) return
    const atBottom = el.scrollHeight - el.scrollTop - el.clientHeight < 40
    setAutoScroll(atBottom)
  }

  return (
    <div className="converter-logs-wrapper">
      <div className="converter-logs-header">
        <span>Logs</span>
        {!autoScroll && (
          <button
            className="converter-scroll-btn"
            onClick={() => {
              setAutoScroll(true)
              bottomRef.current?.scrollIntoView({ behavior: 'smooth' })
            }}
          >
            Scroll to bottom
          </button>
        )}
      </div>
      <div
        className="converter-logs"
        ref={containerRef}
        onScroll={handleScroll}
      >
        {lines.length === 0 ? (
          <div className="converter-logs-empty">
            {containerState === 'running' ? 'Connecting...' : 'Start converter to see logs'}
          </div>
        ) : (
          lines.map((line, i) => (
            <div key={i} className="converter-log-line">
              {line}
            </div>
          ))
        )}
        <div ref={bottomRef} />
      </div>
    </div>
  )
}
