// frontend/src/hooks/useConversion.ts
import { useState, useEffect, useCallback, useRef } from 'react'
import apiClient from '../api/client'

export interface ConversionProfile {
  task: string
  fps: number
  input_path: string
  output_path: string
  repo_id: string
  camera_topic_map: Record<string, string>
  joint_names: string[]
  state_topic: string
  action_topics_map: Record<string, string>
  task_instruction: string[]
  tags: string[]
}

export interface ConversionJob {
  id: string
  folder: string
  status: 'queued' | 'converting' | 'done' | 'failed'
  message: string
  created_at: string
  finished_at: string | null
}

export interface WatchStatus {
  watching: boolean
  input_path: string | null
}

const DEFAULT_PROFILE: ConversionProfile = {
  task: '',
  fps: 20,
  input_path: '',
  output_path: '',
  repo_id: '',
  camera_topic_map: {},
  joint_names: [],
  state_topic: '/joint_states',
  action_topics_map: { leader: '/joint_states' },
  task_instruction: [],
  tags: [],
}

export function useConversion() {
  const [profileNames, setProfileNames] = useState<string[]>([])
  const [selectedProfile, setSelectedProfile] = useState<string | null>(null)
  const [profileData, setProfileData] = useState<ConversionProfile>(DEFAULT_PROFILE)
  const [watchStatus, setWatchStatus] = useState<WatchStatus>({ watching: false, input_path: null })
  const [jobs, setJobs] = useState<ConversionJob[]>([])
  const [mountedRepos, setMountedRepos] = useState<Record<string, string>>({}) // repo_id -> mount_point
  const [saving, setSaving] = useState(false)
  const eventSourceRef = useRef<EventSource | null>(null)

  // Load profiles list
  const fetchProfiles = useCallback(async () => {
    const res = await apiClient.get<string[]>('/conversion/configs')
    setProfileNames(res.data)
  }, [])

  // Load profile content
  const loadProfile = useCallback(async (name: string) => {
    const res = await apiClient.get<ConversionProfile>(`/conversion/configs/${name}`)
    setSelectedProfile(name)
    setProfileData(res.data)
  }, [])

  // Save current profile
  const saveProfile = useCallback(async (name: string) => {
    setSaving(true)
    try {
      if (profileNames.includes(name)) {
        await apiClient.put(`/conversion/configs/${name}`, { config: profileData })
      } else {
        await apiClient.post('/conversion/configs', { name, config: profileData })
      }
      setSelectedProfile(name)
      await fetchProfiles()
    } finally {
      setSaving(false)
    }
  }, [profileData, profileNames, fetchProfiles])

  // Delete profile
  const deleteProfile = useCallback(async (name: string) => {
    await apiClient.delete(`/conversion/configs/${name}`)
    if (selectedProfile === name) {
      setSelectedProfile(null)
      setProfileData(DEFAULT_PROFILE)
    }
    await fetchProfiles()
  }, [selectedProfile, fetchProfiles])

  // Watch control
  const fetchWatchStatus = useCallback(async () => {
    const res = await apiClient.get<WatchStatus>('/conversion/watch/status')
    setWatchStatus(res.data)
  }, [])

  const startWatch = useCallback(async (profileName: string) => {
    await apiClient.post('/conversion/watch/start', { profile_name: profileName })
    await fetchWatchStatus()
  }, [fetchWatchStatus])

  const stopWatch = useCallback(async () => {
    await apiClient.post('/conversion/watch/stop')
    await fetchWatchStatus()
  }, [fetchWatchStatus])

  // Manual run
  const runOnce = useCallback(async (profileName: string) => {
    await apiClient.post('/conversion/run', { profile_name: profileName })
  }, [])

  // Mounted repos from hf-sync
  const fetchMountedRepos = useCallback(async () => {
    try {
      const res = await apiClient.get<{ mounted_repos: string[]; mount_details: Record<string, { mount_point: string }> }>('/hf-sync/status')
      const details = res.data.mount_details ?? {}
      const map: Record<string, string> = {}
      for (const [repoId, d] of Object.entries(details)) {
        map[repoId] = d.mount_point ?? ''
      }
      setMountedRepos(map)
    } catch {
      // hf-sync not available — ignore
    }
  }, [])

  // SSE job stream
  useEffect(() => {
    const es = new EventSource('/api/conversion/jobs/stream')
    eventSourceRef.current = es
    es.onmessage = (e) => {
      try {
        setJobs(JSON.parse(e.data))
      } catch { /* ignore parse errors */ }
    }
    return () => {
      es.close()
      eventSourceRef.current = null
    }
  }, [])

  // Initial load
  useEffect(() => {
    void fetchProfiles()
    void fetchWatchStatus()
    void fetchMountedRepos()
  }, [fetchProfiles, fetchWatchStatus, fetchMountedRepos])

  return {
    profileNames,
    selectedProfile,
    profileData,
    setProfileData,
    watchStatus,
    jobs,
    mountedRepos,
    saving,
    loadProfile,
    saveProfile,
    deleteProfile,
    startWatch,
    stopWatch,
    runOnce,
    fetchMountedRepos,
  }
}
