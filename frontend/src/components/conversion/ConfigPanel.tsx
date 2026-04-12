// frontend/src/components/conversion/ConfigPanel.tsx
import React, { useState } from 'react'
import type { ConversionProfile } from '../../hooks/useConversion'

interface Props {
  profileNames: string[]
  selectedProfile: string | null
  profileData: ConversionProfile
  mountedRepos: Record<string, string>
  saving: boolean
  onProfileSelect: (name: string) => void
  onProfileChange: (data: ConversionProfile) => void
  onSave: (name: string) => void
  onDelete: (name: string) => void
}

export function ConfigPanel({
  profileNames, selectedProfile, profileData, mountedRepos,
  saving, onProfileSelect, onProfileChange, onSave, onDelete,
}: Props) {
  const [newProfileName, setNewProfileName] = useState('')
  const [showNewInput, setShowNewInput] = useState(false)
  const [newCamKey, setNewCamKey] = useState('')
  const [newCamVal, setNewCamVal] = useState('')
  const [newJoint, setNewJoint] = useState('')
  const [newInstruction, setNewInstruction] = useState('')

  const update = (patch: Partial<ConversionProfile>) =>
    onProfileChange({ ...profileData, ...patch })

  const handleRepoSelect = (repoId: string) => {
    const mountPoint = mountedRepos[repoId] ?? ''
    update({ repo_id: repoId, output_path: mountPoint })
  }

  const addCamera = () => {
    if (!newCamKey.trim()) return
    update({
      camera_topic_map: { ...profileData.camera_topic_map, [newCamKey.trim()]: newCamVal.trim() }
    })
    setNewCamKey(''); setNewCamVal('')
  }

  const removeCamera = (key: string) => {
    const m = { ...profileData.camera_topic_map }
    delete m[key]
    update({ camera_topic_map: m })
  }

  const addJoint = () => {
    if (!newJoint.trim()) return
    update({ joint_names: [...profileData.joint_names, newJoint.trim()] })
    setNewJoint('')
  }

  const removeJoint = (j: string) =>
    update({ joint_names: profileData.joint_names.filter(x => x !== j) })

  const addInstruction = () => {
    if (!newInstruction.trim()) return
    update({ task_instruction: [...profileData.task_instruction, newInstruction.trim()] })
    setNewInstruction('')
  }

  const removeInstruction = (i: number) =>
    update({ task_instruction: profileData.task_instruction.filter((_, idx) => idx !== i) })

  const handleSave = () => {
    const name = selectedProfile ?? newProfileName.trim()
    if (!name) { setShowNewInput(true); return }
    onSave(name)
    setShowNewInput(false)
    setNewProfileName('')
  }

  return (
    <div className="conversion-config-panel">
      {/* Profile selector */}
      <div className="conversion-section conversion-profile-bar">
        <label className="conversion-label">Config Profile</label>
        <div className="conversion-profile-row">
          <select
            className="conversion-select"
            value={selectedProfile ?? ''}
            onChange={e => e.target.value && onProfileSelect(e.target.value)}
          >
            <option value="">— select profile —</option>
            {profileNames.map(n => <option key={n} value={n}>{n}</option>)}
          </select>
          <button className="btn-sm" onClick={() => setShowNewInput(v => !v)}>+ New</button>
          {selectedProfile && (
            <button className="btn-sm btn-danger" onClick={() => onDelete(selectedProfile)}>🗑</button>
          )}
        </div>
        {showNewInput && (
          <div className="conversion-new-profile-row">
            <input
              className="conversion-input"
              placeholder="profile name"
              value={newProfileName}
              onChange={e => setNewProfileName(e.target.value)}
              onKeyDown={e => e.key === 'Enter' && handleSave()}
            />
          </div>
        )}
      </div>

      {/* Source */}
      <div className="conversion-section">
        <label className="conversion-label">Source</label>
        <div className="conversion-field">
          <span className="conversion-field-label">Input Path</span>
          <input
            className="conversion-input"
            value={profileData.input_path}
            onChange={e => update({ input_path: e.target.value })}
            placeholder="/path/to/mcap/folders"
          />
        </div>
      </div>

      {/* Target HF repo */}
      <div className="conversion-section">
        <label className="conversion-label">Target HF Repository</label>
        <div className="conversion-repo-list">
          {Object.entries(mountedRepos).map(([repoId, mountPoint]) => (
            <div
              key={repoId}
              className={`conversion-repo-item ${profileData.repo_id === repoId ? 'selected' : ''}`}
              onClick={() => handleRepoSelect(repoId)}
            >
              <span className="conversion-repo-dot mounted" />
              <div>
                <div className="conversion-repo-name">{repoId}</div>
                <div className="conversion-repo-mount">{mountPoint}</div>
              </div>
              {profileData.repo_id === repoId && <span className="conversion-repo-check">✓</span>}
            </div>
          ))}
          <div className="conversion-repo-create" onClick={() => {
            const id = prompt('New repo_id (e.g. org/name):')
            if (id) update({ repo_id: id, output_path: '' })
          }}>
            <span>+</span> 새 저장소 생성
          </div>
        </div>
      </div>

      {/* Config fields */}
      <div className="conversion-section">
        <label className="conversion-label">Config</label>
        <div className="conversion-row-2col">
          <div className="conversion-field">
            <span className="conversion-field-label">Task Name</span>
            <input className="conversion-input" value={profileData.task}
              onChange={e => update({ task: e.target.value })} />
          </div>
          <div className="conversion-field">
            <span className="conversion-field-label">FPS</span>
            <input className="conversion-input" type="number" value={profileData.fps}
              onChange={e => update({ fps: Number(e.target.value) })} style={{ width: 60 }} />
          </div>
        </div>

        {/* Camera Topics */}
        <div className="conversion-field">
          <span className="conversion-field-label">Camera Topics</span>
          {Object.entries(profileData.camera_topic_map).map(([k, v]) => (
            <div key={k} className="conversion-kv-row">
              <input className="conversion-input conversion-key-input" value={k} readOnly />
              <span className="conversion-arrow">→</span>
              <input className="conversion-input" value={v}
                onChange={e => update({ camera_topic_map: { ...profileData.camera_topic_map, [k]: e.target.value } })} />
              <button className="btn-xs btn-danger" onClick={() => removeCamera(k)}>✕</button>
            </div>
          ))}
          <div className="conversion-kv-row">
            <input className="conversion-input conversion-key-input" placeholder="cam_name"
              value={newCamKey} onChange={e => setNewCamKey(e.target.value)} />
            <span className="conversion-arrow">→</span>
            <input className="conversion-input" placeholder="/topic"
              value={newCamVal} onChange={e => setNewCamVal(e.target.value)}
              onKeyDown={e => e.key === 'Enter' && addCamera()} />
            <button className="btn-xs" onClick={addCamera}>+</button>
          </div>
        </div>

        {/* Joint Names */}
        <div className="conversion-field">
          <span className="conversion-field-label">Joint Names</span>
          <div className="conversion-tags">
            {profileData.joint_names.map(j => (
              <span key={j} className="conversion-tag">
                {j} <button className="tag-remove" onClick={() => removeJoint(j)}>✕</button>
              </span>
            ))}
            <div className="conversion-tag-input-row">
              <input className="conversion-input conversion-tag-input" placeholder="joint_name"
                value={newJoint} onChange={e => setNewJoint(e.target.value)}
                onKeyDown={e => e.key === 'Enter' && addJoint()} />
              <button className="btn-xs" onClick={addJoint}>+</button>
            </div>
          </div>
        </div>

        {/* Task Instructions */}
        <div className="conversion-field">
          <span className="conversion-field-label">Task Instructions</span>
          {profileData.task_instruction.map((inst, i) => (
            <div key={i} className="conversion-kv-row">
              <input className="conversion-input" value={inst}
                onChange={e => {
                  const arr = [...profileData.task_instruction]
                  arr[i] = e.target.value
                  update({ task_instruction: arr })
                }} />
              <button className="btn-xs btn-danger" onClick={() => removeInstruction(i)}>✕</button>
            </div>
          ))}
          <div className="conversion-kv-row">
            <input className="conversion-input" placeholder="Add instruction..."
              value={newInstruction} onChange={e => setNewInstruction(e.target.value)}
              onKeyDown={e => e.key === 'Enter' && addInstruction()} />
            <button className="btn-xs" onClick={addInstruction}>+</button>
          </div>
        </div>
      </div>

      {/* Save */}
      <div className="conversion-save-bar">
        <button className="btn-primary" onClick={handleSave} disabled={saving}>
          {saving ? 'Saving...' : '💾 Save Config'}
        </button>
      </div>
    </div>
  )
}
