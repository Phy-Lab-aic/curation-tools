import { useEffect, useRef, useState } from 'react'

interface GradeReasonModalProps {
  open: boolean
  grade: 'normal' | 'bad'
  initialReason?: string
  episodeCount?: number
  onSave: (reason: string) => void
  onCancel: () => void
}

const GRADE_COLORS: Record<'normal' | 'bad', string> = {
  normal: 'var(--c-yellow)',
  bad: 'var(--c-red)',
}

const GRADE_TITLES: Record<'normal' | 'bad', string> = {
  normal: 'Mark as Normal',
  bad: 'Mark as Bad',
}

export function GradeReasonModal({
  open,
  grade,
  initialReason = '',
  episodeCount,
  onSave,
  onCancel,
}: GradeReasonModalProps) {
  const [reason, setReason] = useState(initialReason)
  const textareaRef = useRef<HTMLTextAreaElement>(null)

  // Reset reason whenever the modal (re)opens with a new initial value.
  useEffect(() => {
    if (open) {
      setReason(initialReason)
      // Defer focus until the textarea is mounted.
      requestAnimationFrame(() => textareaRef.current?.focus())
    }
  }, [open, initialReason])

  if (!open) return null

  const trimmed = reason.trim()
  const canSave = trimmed.length > 0
  const color = GRADE_COLORS[grade]
  const title = GRADE_TITLES[grade]
  const isBulk = (episodeCount ?? 1) > 1

  const handleKeyDown = (e: React.KeyboardEvent<HTMLTextAreaElement>) => {
    if (e.key === 'Escape') {
      e.preventDefault()
      onCancel()
      return
    }
    if (e.key === 'Enter' && (e.metaKey || e.ctrlKey)) {
      e.preventDefault()
      if (canSave) onSave(trimmed)
    }
    // Plain Enter falls through → newline (default textarea behavior).
  }

  return (
    <div
      className="grade-reason-overlay"
      onClick={onCancel}
      role="dialog"
      aria-modal="true"
    >
      <div
        className="grade-reason-panel"
        onClick={(e) => e.stopPropagation()}
        style={{ borderTopColor: color }}
      >
        <div className="grade-reason-header" style={{ color }}>
          {title}
        </div>
        {isBulk && (
          <div className="grade-reason-subheader">
            Apply to {episodeCount} episodes
          </div>
        )}
        <textarea
          ref={textareaRef}
          className="grade-reason-textarea"
          rows={5}
          value={reason}
          placeholder="Why is this episode being graded this way?"
          onChange={(e) => setReason(e.target.value)}
          onKeyDown={handleKeyDown}
        />
        <div className="grade-reason-footer">
          <span className="grade-reason-hint">
            <kbd>Esc</kbd> cancel · <kbd>⌘/Ctrl+Enter</kbd> save
          </span>
          <div className="grade-reason-actions">
            <button className="grade-reason-btn" onClick={onCancel}>
              Cancel
            </button>
            <button
              className="grade-reason-btn primary"
              disabled={!canSave}
              onClick={() => canSave && onSave(trimmed)}
              style={{ background: canSave ? color : undefined }}
            >
              Save
            </button>
          </div>
        </div>
      </div>
    </div>
  )
}
