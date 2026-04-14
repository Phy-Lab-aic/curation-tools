import type { DatasetTab } from '../types'

interface DatasetPageProps {
  datasetPath: string
  datasetName: string
  tab: DatasetTab
}

export function DatasetPage({ datasetPath, datasetName, tab }: DatasetPageProps) {
  return (
    <div style={{ padding: 20, color: 'var(--text-muted)', fontSize: 12 }}>
      <div>Dataset: <strong style={{ color: 'var(--text)' }}>{datasetName}</strong></div>
      <div>Path: <code>{datasetPath}</code></div>
      <div style={{ marginTop: 12 }}>Tab: {tab} (coming soon)</div>
    </div>
  )
}
