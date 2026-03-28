import { useState, useCallback } from 'react'
import { DatasetLoader } from './components/DatasetLoader'
import { EpisodeList } from './components/EpisodeList'
import { EpisodeEditor } from './components/EpisodeEditor'
import { TaskEditor } from './components/TaskEditor'
import { RerunViewer } from './components/RerunViewer'
import { useEpisodes } from './hooks/useEpisodes'
import type { DatasetInfo, Episode } from './types'
import './App.css'

export default function App() {
  const [_dataset, setDataset] = useState<DatasetInfo | null>(null)
  const [selectedEpisode, setSelectedEpisode] = useState<Episode | null>(null)
  const [episodeListKey, setEpisodeListKey] = useState(0)
  const { updateEpisode } = useEpisodes()

  const handleDatasetLoaded = useCallback((dataset: DatasetInfo) => {
    setDataset(dataset)
    setSelectedEpisode(null)
    setEpisodeListKey(k => k + 1)
  }, [])

  const handleEpisodeSelect = useCallback((episode: Episode) => {
    setSelectedEpisode(episode)
  }, [])

  const handleSaveEpisode = useCallback(async (index: number, grade: string | null, tags: string[]) => {
    await updateEpisode(index, grade, tags)
    // Update local selected episode to reflect saved state
    setSelectedEpisode(prev =>
      prev?.episode_index === index ? { ...prev, grade, tags } : prev
    )
  }, [updateEpisode])

  return (
    <div className="app-layout">
      <aside className="sidebar">
        <DatasetLoader onDatasetLoaded={handleDatasetLoaded} />
        <EpisodeList
          onEpisodeSelect={handleEpisodeSelect}
          selectedIndex={selectedEpisode?.episode_index ?? null}
          refreshKey={episodeListKey}
        />
      </aside>

      <main className="center-panel">
        <RerunViewer episodeIndex={selectedEpisode?.episode_index ?? null} />
      </main>

      <aside className="right-panel">
        <EpisodeEditor
          episode={selectedEpisode}
          onSave={handleSaveEpisode}
        />
        <TaskEditor episode={selectedEpisode} />
      </aside>
    </div>
  )
}
