import { useEffect, useState } from 'react'
import type { AppState, DatasetTab, ConverterState } from '../types'

interface TopNavProps {
  state: AppState
  onNavigateHome: () => void
  onNavigateCell: (cellName: string, cellPath: string) => void
  onTabChange?: (tab: DatasetTab) => void
  onNavigateConverter?: () => void
}

const TABS: { id: DatasetTab; label: string }[] = [
  { id: 'overview', label: 'Overview' },
  { id: 'curate',   label: 'Curate' },
  { id: 'fields',   label: 'Fields' },
]

const DOT_CLASS: Record<ConverterState, string> = {
  running: 'converter-dot-running',
  stopped: 'converter-dot-stopped',
  building: 'converter-dot-building',
  error: 'converter-dot-error',
  unknown: 'converter-dot-stopped',
}

export function TopNav({ state, onNavigateHome, onNavigateCell, onTabChange, onNavigateConverter }: TopNavProps) {
  const [converterState, setConverterState] = useState<ConverterState>('unknown')

  useEffect(() => {
    const poll = async () => {
      try {
        const res = await fetch('/api/converter/status')
        if (res.ok) {
          const data = await res.json()
          setConverterState(data.container_state)
        }
      } catch {
        setConverterState('unknown')
      }
    }
    poll()
    const id = setInterval(poll, 5000)
    return () => clearInterval(id)
  }, [])

  return (
    <nav className="top-nav">
      <button className="top-nav-logo" onClick={onNavigateHome}>
        robo<span>data</span>
      </button>

      <button
        className={`converter-indicator ${DOT_CLASS[converterState]}`}
        onClick={onNavigateConverter}
        title={`Converter: ${converterState}`}
      >
        <span className="converter-nav-dot" />
      </button>

      <div className="top-nav-breadcrumb">
        {(state.view === 'cell' || state.view === 'dataset') && (
          <>
            <span className="sep">/</span>
            <button onClick={() => onNavigateCell(state.cellName, state.cellPath)}>
              <em>{state.cellName}</em>
            </button>
          </>
        )}
        {state.view === 'dataset' && (
          <>
            <span className="sep">/</span>
            <em>{state.datasetName}</em>
          </>
        )}
        {state.view === 'converter' && (
          <>
            <span className="sep">/</span>
            <em>Converter</em>
          </>
        )}
      </div>

      {state.view === 'dataset' && (
        <div className="top-nav-tabs">
          {TABS.map(tab => (
            <button
              key={tab.id}
              className={`top-nav-tab${state.tab === tab.id ? ' active' : ''}`}
              onClick={() => onTabChange?.(tab.id)}
            >
              {tab.label}
            </button>
          ))}
        </div>
      )}
    </nav>
  )
}
