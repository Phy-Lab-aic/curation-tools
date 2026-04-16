import { useState, useEffect } from 'react'
import type { Episode } from '../types'

interface EpisodeEditorProps {
  episode: Episode | null
  onSave: (index: number, grade: string | null, tags: string[]) => Promise<void>
}

export function EpisodeEditor({ episode, onSave }: EpisodeEditorProps) {
  const [tags, setTags] = useState<string[]>([])
  const [saving, setSaving] = useState(false)
  const [tagInput, setTagInput] = useState('')
  const [showTagInput, setShowTagInput] = useState(false)

  useEffect(() => {
    if (episode) {
      setTags(episode.tags)
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
      {episode.created_at && (
        <div className="ep-details-row">
          <span className="ep-details-key">created</span>
          <span className="ep-details-val">{episode.created_at}</span>
        </div>
      )}
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
      {saving && <div style={{ fontSize: 11, color: 'var(--text-muted)', marginTop: 4 }}>saving...</div>}

      {/* Tags */}
      <div style={{ marginTop: 10 }}>
        <div style={{ fontSize: 10, color: 'var(--text-dim)', textTransform: 'uppercase', letterSpacing: '0.06em', marginBottom: 5 }}>Tags</div>
        <div className="tag-chips">
          {tags.map(tag => (
            <span key={tag} className="tag-chip">
              {tag}
              <button className="tag-chip-remove" onClick={() => removeTag(tag)}>×</button>
            </span>
          ))}
          {showTagInput ? (
            <input
              className="tag-chip"
              style={{ minWidth: 60, outline: 'none', background: 'var(--panel2)', color: 'var(--text)', border: '1px solid var(--accent)', borderRadius: 3, padding: '2px 6px', fontSize: 12 }}
              autoFocus
              value={tagInput}
              onChange={e => setTagInput(e.target.value)}
              onKeyDown={e => {
                if (e.key === 'Enter') {
                  addTag(tagInput)
                  setTagInput('')
                  setShowTagInput(false)
                } else if (e.key === 'Escape') {
                  setTagInput('')
                  setShowTagInput(false)
                }
              }}
              onBlur={() => {
                if (tagInput.trim()) addTag(tagInput)
                setTagInput('')
                setShowTagInput(false)
              }}
            />
          ) : (
            <button
              className="tag-add-chip"
              onClick={() => setShowTagInput(true)}
            >
              + add
            </button>
          )}
        </div>
      </div>
    </div>
  )
}
