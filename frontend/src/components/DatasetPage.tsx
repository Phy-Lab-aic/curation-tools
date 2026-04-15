import { useState, useCallback, useEffect, useRef, useMemo } from 'react'
import { EpisodeList } from './EpisodeList'
import { EpisodeEditor } from './EpisodeEditor'
import { VideoPlayer, type VideoPlayerHandle } from './VideoPlayer'
import { ScalarChart } from './ScalarChart'
import { TrimPanel } from './TrimPanel'
import { useDataset } from '../hooks/useDataset'
import { useEpisodes } from '../hooks/useEpisodes'
import { OverviewTab } from './OverviewTab'
import { FieldsTab } from './FieldsTab'
import type { CurateFilter, DatasetTab, Episode } from '../types'

interface DatasetPageProps {
  datasetPath: string
  datasetName: string
  tab: DatasetTab
  filter?: CurateFilter
  onSetTab: (tab: DatasetTab, filter?: CurateFilter) => void
}

const GRADE_KEYS: Record<string, string> = { '1': 'good', '2': 'normal', '3': 'bad' }

export function DatasetPage({ datasetPath, datasetName: _datasetName, tab, filter, onSetTab }: DatasetPageProps) {
  const { dataset, loadDataset } = useDataset()
  const { episodes, loading: epLoading, error: epError, fetchEpisodes, updateEpisode } = useEpisodes()
  const [selectedEpisode, setSelectedEpisode] = useState<Episode | null>(null)
  const [currentFrame, setCurrentFrame] = useState(0)
  const [terminalFrames, setTerminalFrames] = useState<number[]>([])
  const [terminalTimestamps, setTerminalTimestamps] = useState<number[]>([])
  const [rightTab, setRightTab] = useState<'details' | 'trim'>('details')
  const videoRef = useRef<VideoPlayerHandle>(null)

  // Load dataset when path changes
  useEffect(() => {
    let cancelled = false
    async function init() {
      await loadDataset(datasetPath)
      if (!cancelled) {
        await fetchEpisodes()
      }
    }
    void init()
    return () => { cancelled = true }
  }, [datasetPath, loadDataset, fetchEpisodes])

  const ungradedEpisodes = useMemo(() => episodes.filter(e => !e.grade), [episodes])

  const handleSaveEpisode = useCallback(async (index: number, grade: string | null, tags: string[]) => {
    await updateEpisode(index, grade, tags)
    if (grade) {
      const currentIdx = episodes.findIndex(e => e.episode_index === index)
      const nextUngraded = ungradedEpisodes.find(e => {
        const i = episodes.indexOf(e)
        return i > currentIdx
      }) ?? ungradedEpisodes.find(e => {
        const i = episodes.indexOf(e)
        return i < currentIdx
      })
      if (nextUngraded) {
        setSelectedEpisode(nextUngraded)
        return
      }
    }
    setSelectedEpisode(prev =>
      prev?.episode_index === index ? { ...prev, grade, tags } : prev
    )
  }, [updateEpisode, episodes, ungradedEpisodes])

  const navigateEpisode = useCallback((direction: -1 | 1) => {
    if (!selectedEpisode || episodes.length === 0) return
    const idx = episodes.findIndex(e => e.episode_index === selectedEpisode.episode_index)
    const next = episodes[idx + direction]
    if (next) setSelectedEpisode(next)
  }, [selectedEpisode, episodes])

  const quickGrade = useCallback(async (key: string) => {
    if (!selectedEpisode) return
    const grade = GRADE_KEYS[key]
    if (grade) await handleSaveEpisode(selectedEpisode.episode_index, grade, selectedEpisode.tags)
  }, [selectedEpisode, handleSaveEpisode])

  // Keyboard shortcuts
  useEffect(() => {
    const handler = (e: KeyboardEvent) => {
      const tag = (e.target as HTMLElement)?.tagName
      if (tag === 'INPUT' || tag === 'TEXTAREA' || tag === 'SELECT') return
      switch (e.key) {
        case 'ArrowUp':
        case 'k':
          e.preventDefault(); navigateEpisode(-1); break
        case 'ArrowDown':
        case 'j':
          e.preventDefault(); navigateEpisode(1); break
        case 'ArrowLeft':
          e.preventDefault(); videoRef.current?.stepFrame(-1); break
        case 'ArrowRight':
          e.preventDefault(); videoRef.current?.stepFrame(1); break
        case ' ':
          e.preventDefault(); videoRef.current?.togglePlay(); break
        case '1':
        case '2':
        case '3':
          e.preventDefault(); void quickGrade(e.key); break
      }
    }
    window.addEventListener('keydown', handler)
    return () => window.removeEventListener('keydown', handler)
  }, [navigateEpisode, quickGrade])

  if (tab === 'overview') {
    return (
      <div className="dataset-page">
        <OverviewTab datasetPath={datasetPath} fps={dataset?.fps ?? 30} episodes={episodes} />
      </div>
    )
  }

  if (tab === 'fields') {
    return (
      <div className="dataset-page">
        <FieldsTab datasetPath={datasetPath} />
      </div>
    )
  }

  return (
    <div className="dataset-page">
      <div className="curate-layout">
        {/* Left: episode list */}
        <div className="episode-sidebar">
          <EpisodeList
            episodes={episodes}
            loading={epLoading}
            error={epError}
            onEpisodeSelect={setSelectedEpisode}
            selectedIndex={selectedEpisode?.episode_index ?? null}
          />
        </div>

        {/* Center: video + grade */}
        <div className="curate-center">
          <VideoPlayer
            ref={videoRef}
            episodeIndex={selectedEpisode?.episode_index ?? null}
            fps={dataset?.fps ?? 30}
            onFrameChange={setCurrentFrame}
            terminalFrames={terminalFrames}
          />

          {/* Terminal frames */}
          {selectedEpisode && terminalFrames.length > 0 && (
            <div className="terminal-bar">
              <span className="terminal-bar-label">Terminal ({terminalFrames.length}):</span>
              {terminalFrames.map((f, i) => {
                const ts = terminalTimestamps[i]
                const label = ts != null ? `${ts.toFixed(2)}s` : `f${f}`
                return (
                  <button
                    key={f}
                    className={`terminal-frame-chip${currentFrame === f ? ' active' : ''}`}
                    onClick={() => ts != null
                      ? videoRef.current?.seekToTimestamp(ts)
                      : videoRef.current?.seekToFrame(f)
                    }
                  >
                    {label}
                  </button>
                )
              })}
            </div>
          )}

          {/* Grade bar */}
          {selectedEpisode && (
            <div className="grade-bar">
              {(['good', 'normal', 'bad'] as const).map(g => (
                <button
                  key={g}
                  className={`grade-btn${selectedEpisode.grade === g ? ' active' : ''}`}
                  onClick={() => handleSaveEpisode(selectedEpisode.episode_index, g, selectedEpisode.tags)}
                  style={{
                    color: selectedEpisode.grade === g ? (g === 'good' ? 'var(--c-green)' : g === 'normal' ? 'var(--c-yellow)' : 'var(--c-red)') : undefined,
                    borderBottomColor: selectedEpisode.grade === g ? (g === 'good' ? 'var(--c-green)' : g === 'normal' ? 'var(--c-yellow)' : 'var(--c-red)') : undefined,
                  }}
                >
                  {g}
                </button>
              ))}
              <div className="grade-kbd-hint">
                <kbd>1</kbd><kbd>2</kbd><kbd>3</kbd>
              </div>
            </div>
          )}
        </div>

        {/* Right: details / split-merge */}
        <div className="curate-right">
          <div className="right-tabs">
            <button
              className={`right-tab${rightTab === 'details' ? ' active' : ''}`}
              onClick={() => setRightTab('details')}
            >
              Details
            </button>
            <button
              className={`right-tab${rightTab === 'trim' ? ' active' : ''}`}
              onClick={() => setRightTab('trim')}
            >
              Trim
            </button>
          </div>

          {rightTab === 'details' && (
            <div style={{ flex: 1, overflowY: 'auto' }}>
              <EpisodeEditor episode={selectedEpisode} onSave={handleSaveEpisode} />
              <ScalarChart
                episodeIndex={selectedEpisode?.episode_index ?? null}
                currentFrame={currentFrame}
                onTerminalFrames={(frames, timestamps) => {
                  setTerminalFrames(frames)
                  setTerminalTimestamps(timestamps)
                }}
              />
            </div>
          )}
          {rightTab === 'trim' && (
            <TrimPanel
              datasetPath={dataset?.path ?? null}
              episodes={episodes}
            />
          )}
        </div>
      </div>
    </div>
  )
}
