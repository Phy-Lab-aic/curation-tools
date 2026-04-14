import { useCallback } from 'react'
import { TopNav } from './components/TopNav'
import { LibraryPage } from './components/LibraryPage'
import { CellPage } from './components/CellPage'
import { DatasetPage } from './components/DatasetPage'
import { useAppState } from './hooks/useAppState'
import type { CellInfo, DatasetSummary } from './types'
import './App.css'

export default function App() {
  const { state, navigateHome, navigateToCell, navigateToDataset, setTab } = useAppState()

  const handleSelectCell = useCallback((cell: CellInfo) => {
    navigateToCell(cell.name, cell.path)
  }, [navigateToCell])

  const handleSelectDataset = useCallback((ds: DatasetSummary) => {
    if (state.view === 'cell') {
      navigateToDataset(state.cellName, state.cellPath, ds.path, ds.name)
    }
  }, [state, navigateToDataset])

  return (
    <div className="app-root">
      <TopNav
        state={state}
        onNavigateHome={navigateHome}
        onNavigateCell={navigateToCell}
        onTabChange={setTab}
      />
      <div className="page-content">
        {state.view === 'library' && (
          <LibraryPage onSelectCell={handleSelectCell} />
        )}
        {state.view === 'cell' && (
          <CellPage
            cellName={state.cellName}
            cellPath={state.cellPath}
            onSelectDataset={handleSelectDataset}
          />
        )}
        {state.view === 'dataset' && (
          <DatasetPage
            datasetPath={state.datasetPath}
            datasetName={state.datasetName}
            tab={state.tab}
          />
        )}
      </div>
    </div>
  )
}
