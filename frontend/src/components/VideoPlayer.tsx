import { useEffect, useState, useRef, useCallback, useImperativeHandle, forwardRef } from 'react'
import client from '../api/client'

interface Camera {
  key: string
  label: string
  url: string
  from_timestamp: number
  to_timestamp: number | null
}

export interface VideoPlayerHandle {
  stepFrame: (direction: 1 | -1) => void
  seekToFrame: (frame: number) => void
  seekToTimestamp: (ts: number) => void
}

interface VideoPlayerProps {
  episodeIndex: number | null
  fps: number
  onFrameChange?: (frame: number) => void
  terminalFrames?: number[]
}

export const VideoPlayer = forwardRef<VideoPlayerHandle, VideoPlayerProps>(function VideoPlayer({ episodeIndex, fps, onFrameChange, terminalFrames = [] }, ref) {
  const [cameras, setCameras] = useState<Camera[]>([])
  const [loading, setLoading] = useState(false)
  const [playing, setPlaying] = useState(false)
  const [currentTime, setCurrentTime] = useState(0)
  const [duration, setDuration] = useState(0)
  const [ready, setReady] = useState(false)
  const [videoStartTime, setVideoStartTime] = useState(0)
  const [videoEndTime, setVideoEndTime] = useState(0)
  const videoRefs = useRef<Map<string, HTMLVideoElement>>(new Map())
  const primaryKeyRef = useRef<string | null>(null)
  const animFrameRef = useRef<number>(0)

  const [defaultRate, setDefaultRate] = useState(() => {
    const saved = localStorage.getItem('curation-default-speed')
    return saved ? parseFloat(saved) : 1
  })
  const [playbackRate, setPlaybackRate] = useState(defaultRate)

  const setAsDefault = useCallback((rate: number) => {
    setDefaultRate(rate)
    localStorage.setItem('curation-default-speed', String(rate))
  }, [])
  const effectiveFps = fps || 30

  // Fetch cameras when episode changes
  useEffect(() => {
    if (episodeIndex === null) {
      setCameras([])
      return
    }
    setLoading(true)
    setPlaying(false)
    setReady(false)
    setCurrentTime(0)
    setDuration(0)
    videoRefs.current.clear()
    primaryKeyRef.current = null

    client.get<Camera[]>(`/videos/${episodeIndex}/cameras`)
      .then(res => {
        setCameras(res.data)
        if (res.data.length > 0) {
          const cam = res.data[0]
          setVideoStartTime(cam.from_timestamp ?? 0)
          setVideoEndTime(cam.to_timestamp ?? 0)
        }
      })
      .catch(() => setCameras([]))
      .finally(() => setLoading(false))
  }, [episodeIndex])

  // Animation frame loop for time display
  const updateTime = useCallback(() => {
    const primary = primaryKeyRef.current ? videoRefs.current.get(primaryKeyRef.current) : null
    if (primary && !primary.paused) {
      setCurrentTime(primary.currentTime)
    }
    animFrameRef.current = requestAnimationFrame(updateTime)
  }, [])

  useEffect(() => {
    animFrameRef.current = requestAnimationFrame(updateTime)
    return () => cancelAnimationFrame(animFrameRef.current)
  }, [updateTime])

  // Register a video element
  const registerVideo = useCallback((el: HTMLVideoElement | null, key: string) => {
    if (!el) return
    videoRefs.current.set(key, el)
    if (!primaryKeyRef.current) {
      primaryKeyRef.current = key
    }
  }, [])

  // Called when a video's metadata is loaded (duration is now valid)
  const handleMetadataLoaded = useCallback((key: string) => {
    if (key === primaryKeyRef.current) {
      const video = videoRefs.current.get(key)
      if (video && isFinite(video.duration)) {
        setDuration(video.duration)
        setReady(true)
        // Seek to episode start within the shared video file
        if (videoStartTime > 0) {
          const videos = Array.from(videoRefs.current.values())
          videos.forEach(v => { v.currentTime = videoStartTime })
          setCurrentTime(videoStartTime)
        }
      }
    }
  }, [videoStartTime])

  const togglePlay = useCallback(() => {
    if (!ready) return
    const videos = Array.from(videoRefs.current.values())
    if (playing) {
      videos.forEach(v => v.pause())
      setPlaying(false)
    } else {
      // Sync all videos to primary's current time before playing
      const primary = primaryKeyRef.current ? videoRefs.current.get(primaryKeyRef.current) : null
      const t = primary?.currentTime ?? 0
      videos.forEach(v => {
        v.currentTime = t
        v.playbackRate = playbackRate
        v.play()
      })
      setPlaying(true)
    }
  }, [playing, ready, playbackRate])

  const seek = useCallback((time: number) => {
    const videos = Array.from(videoRefs.current.values())
    videos.forEach(v => {
      v.currentTime = time
    })
    setCurrentTime(time)
    // Report episode-relative frame index
    onFrameChange?.(Math.max(0, Math.floor((time - videoStartTime) * effectiveFps)))
  }, [onFrameChange, effectiveFps, videoStartTime])

  const stepFrame = useCallback((direction: 1 | -1) => {
    const videos = Array.from(videoRefs.current.values())
    videos.forEach(v => v.pause())
    setPlaying(false)
    const primary = primaryKeyRef.current ? videoRefs.current.get(primaryKeyRef.current) : null
    const cur = primary?.currentTime ?? currentTime
    const endTime = videoEndTime || duration
    const newTime = Math.max(videoStartTime, Math.min(endTime, cur + direction / effectiveFps))
    seek(newTime)
  }, [currentTime, duration, effectiveFps, seek, videoStartTime, videoEndTime])

  const seekToFrame = useCallback((frame: number) => {
    const videos = Array.from(videoRefs.current.values())
    videos.forEach(v => v.pause())
    setPlaying(false)
    seek(videoStartTime + frame / effectiveFps)
  }, [effectiveFps, seek, videoStartTime])

  const seekToTimestamp = useCallback((ts: number) => {
    const videos = Array.from(videoRefs.current.values())
    videos.forEach(v => v.pause())
    setPlaying(false)
    seek(videoStartTime + ts)
  }, [seek, videoStartTime])

  useImperativeHandle(ref, () => ({
    stepFrame,
    seekToFrame,
    seekToTimestamp,
  }), [stepFrame, seekToFrame, seekToTimestamp])

  const changeSpeed = useCallback((rate: number) => {
    setPlaybackRate(rate)
    videoRefs.current.forEach(v => {
      v.playbackRate = rate
      // If paused, start playing at new speed immediately
      if (v.paused && ready) {
        v.play()
      }
    })
    if (!playing && ready) {
      setPlaying(true)
    }
  }, [playing, ready])

  const handleVideoEnd = useCallback(() => {
    setPlaying(false)
    const videos = Array.from(videoRefs.current.values())
    videos.forEach(v => v.pause())
  }, [])

  // Sync secondary videos to primary during playback
  const handlePrimaryTimeUpdate = useCallback(() => {
    const primary = primaryKeyRef.current ? videoRefs.current.get(primaryKeyRef.current) : null
    if (!primary) return
    setCurrentTime(primary.currentTime)
    onFrameChange?.(Math.max(0, Math.floor((primary.currentTime - videoStartTime) * effectiveFps)))
    // Sync other videos if they drift too far
    videoRefs.current.forEach((video, key) => {
      if (key !== primaryKeyRef.current && Math.abs(video.currentTime - primary.currentTime) > 0.1) {
        video.currentTime = primary.currentTime
      }
    })
  }, [onFrameChange, effectiveFps, videoStartTime])

  // Episode-relative frame numbers
  const currentFrame = Math.max(0, Math.floor((currentTime - videoStartTime) * effectiveFps))
  const totalFrames = videoEndTime > 0
    ? Math.floor((videoEndTime - videoStartTime) * effectiveFps)
    : Math.floor(duration * effectiveFps)

  if (episodeIndex === null) {
    return (
      <div style={styles.empty}>
        <div style={styles.emptyIcon}>&#9654;</div>
        <div style={styles.emptyText}>Select an episode to view</div>
        <div style={styles.emptyHint}>Use arrow keys or click from the list</div>
      </div>
    )
  }

  if (loading) {
    return (
      <div style={styles.empty}>
        <div style={styles.emptyText}>Loading cameras...</div>
      </div>
    )
  }

  if (cameras.length === 0) {
    return (
      <div style={styles.empty}>
        <div style={styles.emptyText}>No video streams for episode #{episodeIndex}</div>
      </div>
    )
  }

  const gridCols = cameras.length <= 1 ? 1 : cameras.length <= 4 ? 2 : 3

  return (
    <div style={styles.container}>
      <div style={{
        ...styles.grid,
        gridTemplateColumns: `repeat(${gridCols}, 1fr)`,
      }}>
        {cameras.map((cam, i) => {
          const isPrimary = i === 0
          return (
            <div key={cam.key} style={styles.videoCell}>
              <div style={styles.cameraLabel}>{cam.label}</div>
              <video
                ref={el => registerVideo(el, cam.key)}
                src={cam.url}
                style={styles.video}
                muted
                playsInline
                preload="auto"
                onLoadedMetadata={() => handleMetadataLoaded(cam.key)}
                onEnded={isPrimary ? handleVideoEnd : undefined}
                onTimeUpdate={isPrimary ? handlePrimaryTimeUpdate : undefined}
              />
            </div>
          )
        })}
      </div>

      <div style={styles.controls}>
        <div style={styles.controlsRow}>
          <button style={styles.ctrlBtn} onClick={() => stepFrame(-1)} title="Previous frame (,)">
            &#9664;&#9664;
          </button>
          <button
            style={{
              ...styles.playBtn,
              opacity: ready ? 1 : 0.4,
            }}
            onClick={togglePlay}
            title="Play/Pause (Space)"
            disabled={!ready}
          >
            {playing ? '\u23F8' : '\u25B6'}
          </button>
          <button style={styles.ctrlBtn} onClick={() => stepFrame(1)} title="Next frame (.)">
            &#9654;&#9654;
          </button>

          {terminalFrames.length > 0 && (
            <button
              style={{ ...styles.ctrlBtn, color: '#f38ba8', borderColor: '#4a2a2a' }}
              onClick={() => {
                // Jump to next terminal frame after current position; wrap around
                const next = terminalFrames.find(f => f > currentFrame) ?? terminalFrames[0]
                seekToFrame(next)
              }}
              title={`Jump to next terminal frame (${terminalFrames.length} total)`}
            >
              {'\u23ED'}
            </button>
          )}

          <div style={{ flex: 1, position: 'relative' }}>
            <input
              type="range"
              min={videoStartTime}
              max={videoEndTime || duration || 1}
              step={0.001}
              value={currentTime}
              onChange={e => seek(parseFloat(e.target.value))}
              style={{ ...styles.scrubber, flex: 'none', width: '100%' }}
            />
            {totalFrames > 0 && terminalFrames.map((f, i) => (
              <div
                key={i}
                style={{
                  position: 'absolute',
                  left: `${(f / totalFrames) * 100}%`,
                  top: '50%',
                  transform: 'translate(-50%, -50%)',
                  width: '12px',
                  height: '14px',
                  cursor: 'pointer',
                  display: 'flex',
                  alignItems: 'center',
                  justifyContent: 'center',
                  zIndex: 3,
                }}
                onClick={() => seekToFrame(f)}
                title={`Terminal frame ${f}`}
              >
                <div style={{
                  width: '2px',
                  height: '10px',
                  background: '#f38ba8',
                  opacity: 0.7,
                  borderRadius: '1px',
                  pointerEvents: 'none',
                }} />
              </div>
            ))}
          </div>

          <span style={styles.timeLabel}>
            {Math.max(0, currentTime - videoStartTime).toFixed(1)}s / {((videoEndTime || duration) - videoStartTime).toFixed(1)}s
          </span>

          <div style={styles.speedGroup}>
            {[0.5, 1, 2, 4].map(rate => (
              <button
                key={rate}
                style={{
                  ...styles.speedBtn,
                  ...(playbackRate === rate ? styles.speedActive : {}),
                  ...(defaultRate === rate ? { borderBottom: '2px solid #89b4fa' } : {}),
                }}
                onClick={() => changeSpeed(rate)}
                onDoubleClick={() => setAsDefault(rate)}
                title={`${rate}x${defaultRate === rate ? ' (default)' : ''} — double-click to set as default`}
              >
                {rate}x
              </button>
            ))}
          </div>
        </div>
      </div>
    </div>
  )
})

const styles: Record<string, React.CSSProperties> = {
  container: {
    display: 'flex',
    flexDirection: 'column',
    flex: 1,
    overflow: 'hidden',
    background: '#0a0a0a',
  },
  grid: {
    display: 'grid',
    flex: 1,
    gap: '2px',
    padding: '2px',
    overflow: 'hidden',
    alignItems: 'center',
    background: '#0a0a0a',
  },
  videoCell: {
    position: 'relative',
    overflow: 'hidden',
    borderRadius: '4px',
    background: '#111',
    display: 'flex',
    alignItems: 'center',
    justifyContent: 'center',
  },
  cameraLabel: {
    position: 'absolute',
    top: '6px',
    left: '8px',
    fontSize: '11px',
    fontWeight: 600,
    color: 'rgba(255,255,255,0.7)',
    background: 'rgba(0,0,0,0.5)',
    padding: '2px 8px',
    borderRadius: '3px',
    zIndex: 2,
    textTransform: 'uppercase',
    letterSpacing: '0.05em',
  },
  video: {
    width: '100%',
    height: '100%',
    objectFit: 'contain',
  },
  controls: {
    background: '#151515',
    borderTop: '1px solid #2a2a2a',
    padding: '8px 16px',
    flexShrink: 0,
  },
  controlsRow: {
    display: 'flex',
    alignItems: 'center',
    gap: '8px',
  },
  ctrlBtn: {
    background: 'none',
    border: '1px solid #333',
    borderRadius: '4px',
    color: '#aaa',
    padding: '4px 8px',
    fontSize: '11px',
    cursor: 'pointer',
    lineHeight: 1,
  },
  playBtn: {
    background: '#89b4fa',
    border: 'none',
    borderRadius: '50%',
    color: '#fff',
    width: '32px',
    height: '32px',
    fontSize: '14px',
    cursor: 'pointer',
    display: 'flex',
    alignItems: 'center',
    justifyContent: 'center',
    flexShrink: 0,
  },
  scrubber: {
    flex: 1,
    height: '4px',
    cursor: 'pointer',
    accentColor: '#89b4fa',
  },
  timeLabel: {
    fontSize: '11px',
    color: '#888',
    fontFamily: 'monospace',
    whiteSpace: 'nowrap',
    minWidth: '100px',
    textAlign: 'right',
  },
  speedGroup: {
    display: 'flex',
    gap: '2px',
    marginLeft: '8px',
  },
  speedBtn: {
    background: '#1e1e1e',
    border: '1px solid #333',
    borderRadius: '3px',
    color: '#777',
    fontSize: '10px',
    padding: '2px 6px',
    cursor: 'pointer',
    fontFamily: 'monospace',
  },
  speedActive: {
    background: '#2a3a4a',
    borderColor: '#89b4fa',
    color: '#89b4fa',
  },
  empty: {
    display: 'flex',
    flexDirection: 'column',
    alignItems: 'center',
    justifyContent: 'center',
    flex: 1,
    background: '#0a0a0a',
    color: '#555',
    gap: '8px',
  },
  emptyIcon: {
    fontSize: '48px',
    opacity: 0.3,
  },
  emptyText: {
    fontSize: '14px',
    color: '#666',
  },
  emptyHint: {
    fontSize: '12px',
    color: '#444',
  },
}
