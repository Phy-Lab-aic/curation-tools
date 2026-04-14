import type { AppState, DatasetTab } from '../types'

interface TopNavProps {
  state: AppState
  onNavigateHome: () => void
  onNavigateCell: (cellName: string, cellPath: string) => void
  onTabChange?: (tab: DatasetTab) => void
}

const TABS: { id: DatasetTab; label: string }[] = [
  { id: 'overview', label: 'Overview' },
  { id: 'curate',   label: 'Curate' },
  { id: 'fields',   label: 'Fields' },
  { id: 'ops',      label: 'Ops' },
]

export function TopNav({ state, onNavigateHome, onNavigateCell, onTabChange }: TopNavProps) {
  return (
    <nav className="top-nav">
      <button className="top-nav-logo" onClick={onNavigateHome}>
        robo<span>data</span>
      </button>

      <div className="top-nav-breadcrumb">
        {state.view !== 'library' && (
          <>
            <span className="sep">/</span>
            <button onClick={() => {
              if (state.view === 'cell' || state.view === 'dataset') {
                onNavigateCell(state.cellName, state.cellPath)
              }
            }}>
              <em>{state.view === 'cell' || state.view === 'dataset' ? state.cellName : ''}</em>
            </button>
          </>
        )}
        {state.view === 'dataset' && (
          <>
            <span className="sep">/</span>
            <em>{state.datasetName}</em>
          </>
        )}
      </div>

      {state.view === 'dataset' && onTabChange && (
        <div className="top-nav-tabs">
          {TABS.map(tab => (
            <button
              key={tab.id}
              className={`top-nav-tab${state.tab === tab.id ? ' active' : ''}`}
              onClick={() => onTabChange(tab.id)}
            >
              {tab.label}
            </button>
          ))}
        </div>
      )}
    </nav>
  )
}
