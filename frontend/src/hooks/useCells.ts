import { useState, useCallback } from 'react'
import client from '../api/client'
import type { CellInfo, DatasetSummary } from '../types'

interface UseCellsReturn {
  cells: CellInfo[]
  loading: boolean
  error: string | null
  fetchCells: () => Promise<void>
}

interface UseDatasetsReturn {
  datasets: DatasetSummary[]
  loading: boolean
  error: string | null
  fetchDatasets: (cellPath: string) => Promise<void>
}

export function useCells(): UseCellsReturn {
  const [cells, setCells] = useState<CellInfo[]>([])
  const [loading, setLoading] = useState(false)
  const [error, setError] = useState<string | null>(null)

  const fetchCells = useCallback(async () => {
    setLoading(true)
    setError(null)
    try {
      const resp = await client.get<CellInfo[]>('/cells')
      setCells(resp.data)
    } catch (err) {
      setError(err instanceof Error ? err.message : 'Failed to fetch cells')
    } finally {
      setLoading(false)
    }
  }, [])

  return { cells, loading, error, fetchCells }
}

export function useDatasets(): UseDatasetsReturn {
  const [datasets, setDatasets] = useState<DatasetSummary[]>([])
  const [loading, setLoading] = useState(false)
  const [error, setError] = useState<string | null>(null)

  const fetchDatasets = useCallback(async (cellPath: string) => {
    setLoading(true)
    setError(null)
    try {
      const encoded = encodeURIComponent(cellPath)
      const resp = await client.get<DatasetSummary[]>(`/cells/${encoded}/datasets`)
      setDatasets(resp.data)
    } catch (err) {
      setError(err instanceof Error ? err.message : 'Failed to fetch datasets')
    } finally {
      setLoading(false)
    }
  }, [])

  return { datasets, loading, error, fetchDatasets }
}
