import { useState, useCallback } from 'react'
import client from '../api/client'
import type { FieldInfo, DistributionResult } from '../types'

interface UseDistributionReturn {
  fields: FieldInfo[]
  charts: DistributionResult[]
  loading: boolean
  error: string | null
  fetchFields: (datasetPath: string) => Promise<void>
  addChart: (datasetPath: string, field: string, chartType?: string) => Promise<void>
  removeChart: (field: string) => void
}

export function useDistribution(): UseDistributionReturn {
  const [fields, setFields] = useState<FieldInfo[]>([])
  const [charts, setCharts] = useState<DistributionResult[]>([])
  const [loading, setLoading] = useState(false)
  const [error, setError] = useState<string | null>(null)

  const fetchFields = useCallback(async (datasetPath: string) => {
    setLoading(true)
    setError(null)
    try {
      const resp = await client.get<FieldInfo[]>('/datasets/fields', {
        params: { dataset_path: datasetPath },
      })
      setFields(resp.data)
    } catch (err) {
      setError(err instanceof Error ? err.message : 'Failed to fetch fields')
    } finally {
      setLoading(false)
    }
  }, [])

  const addChart = useCallback(async (datasetPath: string, field: string, chartType = 'auto') => {
    setLoading(true)
    setError(null)
    try {
      const resp = await client.post<DistributionResult>('/datasets/distribution', {
        dataset_path: datasetPath,
        field,
        chart_type: chartType,
      })
      setCharts(prev => {
        const filtered = prev.filter(c => c.field !== field)
        return [...filtered, resp.data]
      })
    } catch (err) {
      setError(err instanceof Error ? err.message : 'Failed to compute distribution')
    } finally {
      setLoading(false)
    }
  }, [])

  const removeChart = useCallback((field: string) => {
    setCharts(prev => prev.filter(c => c.field !== field))
  }, [])

  return { fields, charts, loading, error, fetchFields, addChart, removeChart }
}
