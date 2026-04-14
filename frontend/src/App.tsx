import { useCallback } from 'react'
import { TopNav } from './components/TopNav'
import { LibraryPage } from './components/LibraryPage'
import { CellPage } from './components/CellPage'
import { DatasetPage } from './components/DatasetPage'
import { ConverterPage } from './components/ConverterPage'
import { useAppState } from './hooks/useAppState'
import type { CellInfo, DatasetSummary } from './types'
import './App.css'

export default function App() {
  const { state, navigateHome, navigateToCell, navigateToDataset, navigateToConverter, setTab } = useAppState()

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
        onNavigateConverter={navigateToConverter}
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
        {state.view === 'converter' && (
          <ConverterPage />
        )}
      </div>
    </div>
  )
}
