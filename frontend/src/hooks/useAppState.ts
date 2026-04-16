import { useState, useCallback } from 'react'
import type { AppState, CurateFilter, DatasetTab } from '../types'

interface UseAppStateReturn {
  state: AppState
  navigateHome: () => void
  navigateToCell: (cellName: string, cellPath: string) => void
  navigateToDataset: (cellName: string, cellPath: string, datasetPath: string, datasetName: string) => void
  navigateToConverter: () => void
  setTab: (tab: DatasetTab, filter?: CurateFilter) => void
}

export function useAppState(): UseAppStateReturn {
  const [state, setState] = useState<AppState>({ view: 'library' })

  const navigateHome = useCallback(() => {
    setState({ view: 'library' })
  }, [])

  const navigateToCell = useCallback((cellName: string, cellPath: string) => {
    setState({ view: 'cell', cellName, cellPath })
  }, [])

  const navigateToDataset = useCallback((
    cellName: string,
    cellPath: string,
    datasetPath: string,
    datasetName: string,
  ) => {
    setState({ view: 'dataset', cellName, cellPath, datasetPath, datasetName, tab: 'overview' })
  }, [])

  const navigateToConverter = useCallback(() => {
    setState({ view: 'converter' })
  }, [])

  const setTab = useCallback((tab: DatasetTab, filter?: CurateFilter) => {
    setState(prev =>
      prev.view === 'dataset' ? { ...prev, tab, filter } : prev
    )
  }, [])

  return { state, navigateHome, navigateToCell, navigateToDataset, navigateToConverter, setTab }
}
