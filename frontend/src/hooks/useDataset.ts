import { useState, useCallback, useRef } from 'react'
import axios from 'axios'
import client from '../api/client'
import type { DatasetInfo } from '../types'

interface UseDatasetReturn {
  dataset: DatasetInfo | null
  loading: boolean
  error: string | null
  loadDataset: (path: string) => Promise<void>
}

export function useDataset(): UseDatasetReturn {
  const [dataset, setDataset] = useState<DatasetInfo | null>(null)
  const [loading, setLoading] = useState(false)
  const [error, setError] = useState<string | null>(null)
  const requestIdRef = useRef(0)

  const loadDataset = useCallback(async (path: string) => {
    const requestId = requestIdRef.current + 1
    requestIdRef.current = requestId
    setLoading(true)
    setDataset(null)
    setError(null)
    try {
      const response = await client.post<DatasetInfo>('/datasets/load', { path })
      if (requestId !== requestIdRef.current) return
      setDataset(response.data)
    } catch (err) {
      const message = axios.isAxiosError(err)
        ? (typeof err.response?.data?.detail === 'string' ? err.response.data.detail : err.message)
        : (err instanceof Error ? err.message : 'Failed to load dataset')
      if (requestId !== requestIdRef.current) throw err
      setDataset(null)
      setError(message)
      throw err
    } finally {
      if (requestId === requestIdRef.current) {
        setLoading(false)
      }
    }
  }, [])

  return { dataset, loading, error, loadDataset }
}
