export type VideoRecord = {
  id: string
  fileName: string
  size: number
  durationSeconds: number | null
  createdAt: string
  videoUrl: string | null
  source: 'server' | 'local-demo'
}

const uploadEndpoint = import.meta.env.VITE_VIDEO_UPLOAD_ENDPOINT?.trim() ?? ''
const listEndpoint = import.meta.env.VITE_VIDEO_LIST_ENDPOINT?.trim() || uploadEndpoint
const formField = import.meta.env.VITE_VIDEO_FORM_FIELD?.trim() || 'video'

export const videoApiConfigured = Boolean(uploadEndpoint)
export const videoListConfigured = Boolean(listEndpoint)

function parseRecord(value: unknown, fallback?: { file?: File; durationSeconds?: number | null }): VideoRecord {
  if (!value || typeof value !== 'object') throw new Error('The video service returned an invalid record.')
  const record = value as Record<string, unknown>
  if (typeof record.id !== 'string' || !record.id) throw new Error('The video service response is missing an id.')

  const fileName = typeof record.fileName === 'string' ? record.fileName : fallback?.file?.name
  if (!fileName) throw new Error('The video service response is missing a file name.')

  const size = typeof record.size === 'number' && Number.isFinite(record.size) && record.size >= 0
    ? record.size
    : fallback?.file?.size
  if (typeof size !== 'number') throw new Error('The video service response is missing the file size.')
  const durationSeconds = typeof record.durationSeconds === 'number' && Number.isFinite(record.durationSeconds) && record.durationSeconds >= 0
    ? record.durationSeconds
    : fallback?.durationSeconds ?? null

  return {
    id: record.id,
    fileName,
    size,
    durationSeconds,
    createdAt: typeof record.createdAt === 'string' ? record.createdAt : new Date().toISOString(),
    videoUrl: typeof record.videoUrl === 'string' ? record.videoUrl : null,
    source: 'server',
  }
}

function simulateProgress(onProgress: (progress: number) => void) {
  return new Promise<void>((resolve) => {
    const steps = [12, 28, 47, 69, 86, 100]
    let index = 0
    const timer = window.setInterval(() => {
      onProgress(steps[index])
      index += 1
      if (index === steps.length) {
        window.clearInterval(timer)
        resolve()
      }
    }, 190)
  })
}

export async function uploadVideo(
  file: File,
  durationSeconds: number | null,
  onProgress: (progress: number) => void,
): Promise<VideoRecord> {
  if (!uploadEndpoint) {
    await simulateProgress(onProgress)
    return {
      id: `demo-${crypto.randomUUID()}`,
      fileName: file.name,
      size: file.size,
      durationSeconds,
      createdAt: new Date().toISOString(),
      videoUrl: null,
      source: 'local-demo',
    }
  }

  return new Promise((resolve, reject) => {
    const request = new XMLHttpRequest()
    request.open('POST', uploadEndpoint)
    request.responseType = 'json'
    request.timeout = 10 * 60 * 1000
    request.upload.onprogress = (event) => {
      if (!event.lengthComputable) return
      onProgress(Math.min(94, Math.round((event.loaded / event.total) * 94)))
    }
    request.onload = () => {
      if (request.status < 200 || request.status >= 300) {
        reject(new Error(`Video upload failed (${request.status}).`))
        return
      }
      try {
        const record = parseRecord(request.response, { file, durationSeconds })
        onProgress(100)
        resolve(record)
      } catch (error) {
        reject(error instanceof Error ? error : new Error('The video service returned an invalid response.'))
      }
    }
    request.onerror = () => reject(new Error('Could not reach the video service. Check the connection and try again.'))
    request.ontimeout = () => reject(new Error('The video upload timed out. Try again.'))

    const body = new FormData()
    body.append(formField, file, file.name)
    if (durationSeconds !== null && Number.isFinite(durationSeconds)) body.append('durationSeconds', String(durationSeconds))
    request.send(body)
  })
}

export async function listVideos(): Promise<VideoRecord[]> {
  if (!listEndpoint) return []

  const response = await fetch(listEndpoint, { headers: { Accept: 'application/json' } })
  if (!response.ok) throw new Error(`Could not load investigations (${response.status}).`)
  const payload: unknown = await response.json()
  const records = Array.isArray(payload)
    ? payload
    : payload && typeof payload === 'object' && Array.isArray((payload as { videos?: unknown }).videos)
      ? (payload as { videos: unknown[] }).videos
      : null

  if (!records) throw new Error('The video service response must be a list or an object with a videos list.')
  return records.map((record) => parseRecord(record))
}
