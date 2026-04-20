import { useState, useCallback } from 'react'
import type { AppState, CurateFilter, DatasetTab } from '../types'

interface UseAppStateReturn {
  state: AppState
  navigateHome: () => void
  navigateToSource: (sourceName: string, sourcePath: string) => void
  navigateToCell: (sourceName: string, sourcePath: string, cellName: string, cellPath: string) => void
  navigateToDataset: (
    sourceName: string,
    sourcePath: string,
    cellName: string,
    cellPath: string,
    datasetPath: string,
    datasetName: string,
  ) => void
  navigateToConverter: () => void
  setTab: (tab: DatasetTab, filter?: CurateFilter) => void
}

export function useAppState(): UseAppStateReturn {
  const [state, setState] = useState<AppState>({ view: 'library' })

  const navigateHome = useCallback(() => {
    setState({ view: 'library' })
  }, [])

  const navigateToSource = useCallback((sourceName: string, sourcePath: string) => {
    setState({ view: 'source', sourceName, sourcePath })
  }, [])

  const navigateToCell = useCallback((sourceName: string, sourcePath: string, cellName: string, cellPath: string) => {
    setState({ view: 'cell', sourceName, sourcePath, cellName, cellPath })
  }, [])

  const navigateToDataset = useCallback((
    sourceName: string,
    sourcePath: string,
    cellName: string,
    cellPath: string,
    datasetPath: string,
    datasetName: string,
  ) => {
    setState({
      view: 'dataset',
      sourceName,
      sourcePath,
      cellName,
      cellPath,
      datasetPath,
      datasetName,
      tab: 'overview',
    })
  }, [])

  const navigateToConverter = useCallback(() => {
    setState({ view: 'converter' })
  }, [])

  const setTab = useCallback((tab: DatasetTab, filter?: CurateFilter) => {
    setState(prev =>
      prev.view === 'dataset' ? { ...prev, tab, filter } : prev
    )
  }, [])

  return { state, navigateHome, navigateToSource, navigateToCell, navigateToDataset, navigateToConverter, setTab }
}
