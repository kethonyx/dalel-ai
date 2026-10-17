import { useEffect, useState, type ReactNode } from 'react'

const posterCache = new Map<string, string>()
const sessionPrefix = 'forte-investigation-poster:'

function getCachedPoster(jobId: string) {
  const memoryPoster = posterCache.get(jobId)
  if (memoryPoster) return memoryPoster
  try {
    const storedPoster = sessionStorage.getItem(`${sessionPrefix}${jobId}`)
    if (storedPoster) {
      posterCache.set(jobId, storedPoster)
      return storedPoster
    }
  } catch {
    // Storage can be disabled or full; the in-memory cache still works.
  }
  return ''
}

function cachePoster(jobId: string, poster: string) {
  posterCache.set(jobId, poster)
  try {
    sessionStorage.setItem(`${sessionPrefix}${jobId}`, poster)
  } catch {
    // The poster remains available for the current page session.
  }
}

function normalizeEvidenceFrame(imageBase64: string) {
  return imageBase64.startsWith('data:') ? imageBase64 : `data:image/jpeg;base64,${imageBase64}`
}

export function InvestigationPoster({
  jobId,
  source,
  posterSource,
  file,
  evidenceFrame,
  fallback,
}: {
  jobId: string
  source: string
  posterSource?: string
  file: File | null
  evidenceFrame?: string
  fallback: ReactNode
}) {
  const stateKey = `${jobId}:${source}:${posterSource ?? ''}:${file?.size ?? 0}:${file?.lastModified ?? 0}`
  const [posterState, setPosterState] = useState(() => ({
    key: stateKey,
    image: evidenceFrame ? normalizeEvidenceFrame(evidenceFrame) : getCachedPoster(jobId),
  }))
  const [failedPosterKey, setFailedPosterKey] = useState('')
  const evidencePoster = evidenceFrame ? normalizeEvidenceFrame(evidenceFrame) : ''
  const directPosterFailed = failedPosterKey === `${stateKey}:${posterSource ?? ''}`
  const cachedPoster = getCachedPoster(jobId) || (posterState.key === stateKey ? posterState.image : '')
  const poster = evidencePoster || (posterSource && !directPosterFailed ? '' : cachedPoster)

  useEffect(() => {
    let cancelled = false
    let objectUrl = ''
    let timeout = 0
    if (evidencePoster || (posterSource && !directPosterFailed)) return () => { cancelled = true }
    const cached = getCachedPoster(jobId)
    if (cached) return () => { cancelled = true }
    if (!source && !file) return () => { cancelled = true }

    const videoSource = file ? (objectUrl = URL.createObjectURL(file)) : source
    const video = document.createElement('video')
    video.preload = 'auto'
    video.muted = true
    video.playsInline = true
    video.crossOrigin = 'anonymous'
    video.setAttribute('aria-hidden', 'true')
    Object.assign(video.style, { position: 'fixed', width: '1px', height: '1px', opacity: '0', pointerEvents: 'none', left: '-2px', top: '-2px' })
    document.body.appendChild(video)

    function captureFrame() {
      if (cancelled || !video.videoWidth || !video.videoHeight) return
      const canvas = document.createElement('canvas')
      const scale = Math.min(1, 640 / video.videoWidth)
      canvas.width = Math.max(1, Math.round(video.videoWidth * scale))
      canvas.height = Math.max(1, Math.round(video.videoHeight * scale))
      try {
        const context = canvas.getContext('2d')
        if (!context) return
        context.drawImage(video, 0, 0, canvas.width, canvas.height)
        const image = canvas.toDataURL('image/jpeg', 0.78)
        cachePoster(jobId, image)
        if (!cancelled) setPosterState({ key: stateKey, image })
      } catch {
        // Some browser/codec combinations can't draw the source to canvas.
      }
    }

    video.addEventListener('loadedmetadata', () => {
      if (cancelled || !Number.isFinite(video.duration)) return
      const seekTime = video.duration > 1 ? 1 : Math.max(0, video.duration * 0.5)
      if (seekTime === 0) captureFrame()
      else video.currentTime = seekTime
    }, { once: true })
    video.addEventListener('seeked', captureFrame, { once: true })
    video.addEventListener('loadeddata', () => {
      if (video.currentTime === 0) captureFrame()
    }, { once: true })
    video.src = videoSource
    video.load()
    timeout = window.setTimeout(() => {
      video.pause()
      video.removeAttribute('src')
      video.load()
    }, 25000)

    return () => {
      cancelled = true
      window.clearTimeout(timeout)
      video.pause()
      video.removeAttribute('src')
      video.load()
      video.remove()
      if (objectUrl) URL.revokeObjectURL(objectUrl)
    }
  }, [directPosterFailed, evidenceFrame, evidencePoster, file, jobId, posterSource, source, stateKey])

  return <>{poster ? <img className="investigation-poster-image" src={poster} alt="Video preview frame" /> : posterSource && !directPosterFailed ? <img className="investigation-poster-image" src={posterSource} alt="Video preview frame" onError={() => setFailedPosterKey(`${stateKey}:${posterSource}`)} /> : fallback}</>
}
