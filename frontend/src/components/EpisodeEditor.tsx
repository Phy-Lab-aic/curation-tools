import { useState, useEffect } from 'react'
import type { Episode } from '../types'

const GRADES = ['', 'A', 'B', 'C', 'D', 'F'] as const

const GRADE_COLORS: Record<string, string> = {
  A: '#4caf50',
  B: '#8bc34a',
  C: '#ffc107',
  D: '#ff9800',
  F: '#f44336',
}

interface EpisodeEditorProps {
  episode: Episode | null
  onSave: (index: number, grade: string | null, tags: string[]) => Promise<void>
}

export function EpisodeEditor({ episode, onSave }: EpisodeEditorProps) {
  const [grade, setGrade] = useState<string>('')
  const [tags, setTags] = useState<string[]>([])
  const [tagInput, setTagInput] = useState('')
  const [saving, setSaving] = useState(false)
  const [saveError, setSaveError] = useState<string | null>(null)
  const [saved, setSaved] = useState(false)

  useEffect(() => {
    if (episode) {
      setGrade(episode.grade ?? '')
      setTags(episode.tags)
      setTagInput('')
      setSaveError(null)
      setSaved(false)
    }
  }, [episode])

  const handleAddTag = () => {
    const trimmed = tagInput.trim()
    if (trimmed && !tags.includes(trimmed)) {
      setTags(prev => [...prev, trimmed])
    }
    setTagInput('')
  }

  const handleRemoveTag = (tag: string) => {
    setTags(prev => prev.filter(t => t !== tag))
  }

  const handleTagKeyDown = (e: React.KeyboardEvent) => {
    if (e.key === 'Enter') handleAddTag()
  }

  const handleSave = async () => {
    if (!episode) return
    setSaving(true)
    setSaveError(null)
    setSaved(false)
    try {
      await onSave(episode.episode_index, grade || null, tags)
      setSaved(true)
      setTimeout(() => setSaved(false), 2000)
    } catch (err) {
      setSaveError(err instanceof Error ? err.message : 'Save failed')
    } finally {
      setSaving(false)
    }
  }

  if (!episode) {
    return (
      <div style={styles.container}>
        <div style={styles.title}>Episode</div>
        <div style={styles.empty}>Select an episode to edit</div>
      </div>
    )
  }

  return (
    <div style={styles.container}>
      <div style={styles.titleRow}>
        <span style={styles.title}>Episode #{episode.episode_index}</span>
        <span style={styles.meta}>{episode.length} frames</span>
      </div>

      <div style={styles.field}>
        <label style={styles.label}>Grade</label>
        <select
          style={styles.select}
          value={grade}
          onChange={e => setGrade(e.target.value)}
        >
          {GRADES.map(g => (
            <option key={g} value={g} style={g ? { color: GRADE_COLORS[g] } : {}}>
              {g || 'No grade'}
            </option>
          ))}
        </select>
      </div>

      <div style={styles.field}>
        <label style={styles.label}>Tags</label>
        <div style={styles.tagInputRow}>
          <input
            style={styles.input}
            type="text"
            placeholder="Add tag..."
            value={tagInput}
            onChange={e => setTagInput(e.target.value)}
            onKeyDown={handleTagKeyDown}
          />
          <button style={styles.addButton} onClick={handleAddTag}>Add</button>
        </div>
        <div style={styles.tagChips}>
          {tags.map(tag => (
            <span key={tag} style={styles.chip}>
              {tag}
              <button
                style={styles.chipRemove}
                onClick={() => handleRemoveTag(tag)}
              >
                x
              </button>
            </span>
          ))}
          {tags.length === 0 && <span style={styles.noTags}>No tags</span>}
        </div>
      </div>

      {saveError && <div style={styles.error}>{saveError}</div>}

      <button
        style={{ ...styles.saveButton, opacity: saving ? 0.6 : 1 }}
        onClick={handleSave}
        disabled={saving}
      >
        {saving ? 'Saving...' : saved ? 'Saved!' : 'Save'}
      </button>
    </div>
  )
}

const styles: Record<string, React.CSSProperties> = {
  container: {
    padding: '12px',
    borderBottom: '1px solid #333',
  },
  titleRow: {
    display: 'flex',
    justifyContent: 'space-between',
    alignItems: 'center',
    marginBottom: '12px',
  },
  title: {
    fontSize: '11px',
    fontWeight: 600,
    textTransform: 'uppercase',
    letterSpacing: '0.08em',
    color: '#888',
  },
  meta: {
    fontSize: '11px',
    color: '#666',
  },
  empty: {
    color: '#666',
    fontSize: '13px',
    padding: '8px 0',
  },
  field: {
    marginBottom: '10px',
  },
  label: {
    display: 'block',
    fontSize: '11px',
    color: '#888',
    marginBottom: '4px',
  },
  select: {
    width: '100%',
    background: '#2a2a2a',
    border: '1px solid #444',
    borderRadius: '4px',
    color: '#e0e0e0',
    padding: '6px 8px',
    fontSize: '13px',
  },
  tagInputRow: {
    display: 'flex',
    gap: '6px',
    marginBottom: '6px',
  },
  input: {
    flex: 1,
    background: '#2a2a2a',
    border: '1px solid #444',
    borderRadius: '4px',
    color: '#e0e0e0',
    padding: '5px 8px',
    fontSize: '13px',
    outline: 'none',
  },
  addButton: {
    background: '#3a5a3a',
    border: 'none',
    borderRadius: '4px',
    color: '#8bc34a',
    padding: '5px 10px',
    fontSize: '12px',
    cursor: 'pointer',
  },
  tagChips: {
    display: 'flex',
    flexWrap: 'wrap',
    gap: '4px',
    minHeight: '24px',
  },
  chip: {
    background: '#2a3a4a',
    border: '1px solid #3a5a7a',
    borderRadius: '12px',
    color: '#90caf9',
    fontSize: '12px',
    padding: '2px 8px',
    display: 'flex',
    alignItems: 'center',
    gap: '4px',
  },
  chipRemove: {
    background: 'none',
    border: 'none',
    color: '#666',
    cursor: 'pointer',
    fontSize: '11px',
    padding: '0',
    lineHeight: 1,
  },
  noTags: {
    color: '#555',
    fontSize: '12px',
  },
  error: {
    color: '#e05252',
    fontSize: '12px',
    marginBottom: '8px',
  },
  saveButton: {
    width: '100%',
    background: '#3a6ea5',
    border: 'none',
    borderRadius: '4px',
    color: '#fff',
    padding: '7px',
    fontSize: '13px',
    cursor: 'pointer',
    marginTop: '4px',
  },
}
