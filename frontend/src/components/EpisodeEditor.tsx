import { useState, useEffect } from 'react'
import type { Episode } from '../types'

interface EpisodeEditorProps {
  episode: Episode | null
  onSave: (index: number, grade: string | null, tags: string[]) => Promise<void>
}

export function EpisodeEditor({ episode, onSave }: EpisodeEditorProps) {
  const [tags, setTags] = useState<string[]>([])
  const [tagInput, setTagInput] = useState('')
  const [saving, setSaving] = useState(false)

  useEffect(() => {
    if (episode) {
      setTags(episode.tags)
      setTagInput('')
    }
  }, [episode?.episode_index])

  const saveTags = async (newTags: string[]) => {
    if (!episode) return
    setSaving(true)
    try {
      await onSave(episode.episode_index, episode.grade, newTags)
    } finally {
      setSaving(false)
    }
  }

  const addTag = (tag: string) => {
    const t = tag.trim()
    if (!t || tags.includes(t)) return
    const next = [...tags, t]
    setTags(next)
    void saveTags(next)
  }

  const removeTag = (tag: string) => {
    const next = tags.filter(t => t !== tag)
    setTags(next)
    void saveTags(next)
  }

  if (!episode) {
    return (
      <div className="ep-details" style={{ color: 'var(--text-muted)', fontSize: 12 }}>
        Select an episode
      </div>
    )
  }

  return (
    <div className="ep-details">
      <div className="ep-details-row">
        <span className="ep-details-key">episode</span>
        <span className="ep-details-val" style={{ color: 'var(--accent)' }}>
          ep_{String(episode.episode_index).padStart(3, '0')}
        </span>
      </div>
      <div className="ep-details-row">
        <span className="ep-details-key">length</span>
        <span className="ep-details-val">{episode.length} frames</span>
      </div>
      <div className="ep-details-row">
        <span className="ep-details-key">task</span>
        <span className="ep-details-val" style={{ maxWidth: 120, overflow: 'hidden', textOverflow: 'ellipsis', whiteSpace: 'nowrap' }}>
          {episode.task_instruction || `task_${episode.task_index}`}
        </span>
      </div>
      <div className="ep-details-row">
        <span className="ep-details-key">grade</span>
        <span className="ep-details-val" style={{
          color: episode.grade === 'good' ? 'var(--c-green)'
               : episode.grade === 'normal' ? 'var(--c-yellow)'
               : episode.grade === 'bad' ? 'var(--c-red)'
               : 'var(--text-dim)',
        }}>
          {episode.grade ?? '—'}
        </span>
      </div>
      {saving && <div style={{ fontSize: 10, color: 'var(--text-muted)', marginTop: 4 }}>saving...</div>}

      {/* Tags */}
      <div style={{ marginTop: 10 }}>
        <div style={{ fontSize: 9, color: 'var(--text-dim)', textTransform: 'uppercase', letterSpacing: '0.06em', marginBottom: 5 }}>Tags</div>
        <div className="tag-chips">
          {tags.map(tag => (
            <span key={tag} className="tag-chip">
              {tag}
              <button className="tag-chip-remove" onClick={() => removeTag(tag)}>×</button>
            </span>
          ))}
          <button
            className="tag-add-chip"
            onClick={() => {
              const t = prompt('Tag:')
              if (t) addTag(t)
            }}
          >
            + add
          </button>
        </div>
      </div>
    </div>
  )
}
