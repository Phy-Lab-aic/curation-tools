import { useState, useCallback } from 'react'
import client from '../api/client'
import type { InfoField, EpisodeColumn } from '../types'

interface UseFieldsReturn {
  infoFields: InfoField[]
  episodeColumns: EpisodeColumn[]
  loading: boolean
  error: string | null
  fetchInfoFields: (datasetPath: string) => Promise<void>
  fetchEpisodeColumns: (datasetPath: string) => Promise<void>
  updateInfoField: (datasetPath: string, key: string, value: unknown) => Promise<void>
  deleteInfoField: (datasetPath: string, key: string) => Promise<void>
  addEpisodeColumn: (datasetPath: string, name: string, dtype: string, defaultValue: unknown) => Promise<void>
}

export function useFields(): UseFieldsReturn {
  const [infoFields, setInfoFields] = useState<InfoField[]>([])
  const [episodeColumns, setEpisodeColumns] = useState<EpisodeColumn[]>([])
  const [loading, setLoading] = useState(false)
  const [error, setError] = useState<string | null>(null)

  const fetchInfoFields = useCallback(async (datasetPath: string) => {
    setLoading(true)
    setError(null)
    try {
      const resp = await client.get<InfoField[]>('/datasets/info-fields', {
        params: { dataset_path: datasetPath },
      })
      setInfoFields(resp.data)
    } catch (err) {
      setError(err instanceof Error ? err.message : 'Failed to fetch info fields')
    } finally {
      setLoading(false)
    }
  }, [])

  const fetchEpisodeColumns = useCallback(async (datasetPath: string) => {
    setLoading(true)
    setError(null)
    try {
      const resp = await client.get<EpisodeColumn[]>('/datasets/episode-columns', {
        params: { dataset_path: datasetPath },
      })
      setEpisodeColumns(resp.data)
    } catch (err) {
      setError(err instanceof Error ? err.message : 'Failed to fetch episode columns')
    } finally {
      setLoading(false)
    }
  }, [])

  const updateInfoField = useCallback(async (datasetPath: string, key: string, value: unknown) => {
    try {
      await client.patch('/datasets/info-fields', { key, value }, {
        params: { dataset_path: datasetPath },
      })
      await fetchInfoFields(datasetPath)
    } catch (err) {
      setError(err instanceof Error ? err.message : 'Failed to update field')
    }
  }, [fetchInfoFields])

  const deleteInfoField = useCallback(async (datasetPath: string, key: string) => {
    try {
      await client.patch('/datasets/info-fields', { key, value: null }, {
        params: { dataset_path: datasetPath },
      })
      await fetchInfoFields(datasetPath)
    } catch (err) {
      setError(err instanceof Error ? err.message : 'Failed to delete field')
    }
  }, [fetchInfoFields])

  const addEpisodeColumn = useCallback(async (
    datasetPath: string, name: string, dtype: string, defaultValue: unknown,
  ) => {
    setLoading(true)
    try {
      await client.post('/datasets/episode-columns', {
        dataset_path: datasetPath,
        column_name: name,
        dtype,
        default_value: defaultValue,
      })
      await fetchEpisodeColumns(datasetPath)
    } catch (err) {
      setError(err instanceof Error ? err.message : 'Failed to add column')
    } finally {
      setLoading(false)
    }
  }, [fetchEpisodeColumns])

  return {
    infoFields, episodeColumns, loading, error,
    fetchInfoFields, fetchEpisodeColumns, updateInfoField, deleteInfoField, addEpisodeColumn,
  }
}
