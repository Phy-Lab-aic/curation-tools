import { useCallback, useEffect, useState } from 'react'
import { TopNav } from './components/TopNav'
import { LibraryPage } from './components/LibraryPage'
import { CellPage } from './components/CellPage'
import { DatasetPage } from './components/DatasetPage'
import { ConverterPage } from './components/ConverterPage'
import { useAppState } from './hooks/useAppState'
import type { CellInfo, ConverterStatus, DatasetSummary } from './types'
import './App.css'

export default function App() {
  const { state, navigateHome, navigateToCell, navigateToDataset, navigateToConverter, setTab } = useAppState()

  const [converterStatus, setConverterStatus] = useState<ConverterStatus>({
    container_state: 'unknown', docker_available: false, tasks: [], summary: ''
  })

  const fetchConverterStatus = useCallback(async () => {
    try {
      const res = await fetch('/api/converter/status')
      if (res.ok) setConverterStatus(await res.json())
    } catch {}
  }, [])

  useEffect(() => {
    fetchConverterStatus()
    const id = setInterval(fetchConverterStatus, 5000)
    return () => clearInterval(id)
  }, [fetchConverterStatus])

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
        converterState={converterStatus.container_state}
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
            filter={state.filter}
            onSetTab={setTab}
          />
        )}
        {state.view === 'converter' && (
          <ConverterPage status={converterStatus} onRefresh={fetchConverterStatus} />
        )}
      </div>
    </div>
  )
}
