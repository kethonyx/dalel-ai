export type AnalysisStatus = 'processing' | 'done' | 'failed'

export type UiAnalyzeResponse = {
  video_id: string
  job_id: string
  status: AnalysisStatus
}

export type EvidenceFrame = { timestamp_sec: number; image_base64: string }
export type AnalysisViolation = {
  type: string
  timecode_sec: number
  description: string
  evidence_frames: EvidenceFrame[]
  rule?: { document?: string; section?: string; url?: string } | null
}

export type UiJobResponse = {
  job_id: string
  status: AnalysisStatus
  stage?: string
  progress?: number
  video_id?: string
  stream_url?: string
  verdict?: string
  violations?: AnalysisViolation[]
  error?: string
}

export type StoredInvestigation = {
  videoId: string
  jobId: string
  fileName: string
  size: number
  durationSeconds: number | null
  createdAt: string
  status: AnalysisStatus
  stage: string
  progress: number
  streamUrl: string | null
  verdict: string | null
  violationCount: number
  error: string | null
}

const HISTORY_KEY = 'fortebank-compliance-investigations-v1'

function isAnalysisStatus(value: unknown): value is AnalysisStatus {
  return value === 'processing' || value === 'done' || value === 'failed'
}

function parseAnalyzeResponse(value: unknown): UiAnalyzeResponse {
  if (!value || typeof value !== 'object') throw new Error('The upload response was invalid.')
  const payload = value as Record<string, unknown>
  if (typeof payload.video_id !== 'string' || typeof payload.job_id !== 'string' || !isAnalysisStatus(payload.status)) {
    throw new Error('The upload response is missing required details.')
  }
  return { video_id: payload.video_id, job_id: payload.job_id, status: payload.status }
}

function parseViolations(value: unknown): AnalysisViolation[] | undefined {
  if (!Array.isArray(value)) return undefined
  return value.flatMap((entry) => {
    if (!entry || typeof entry !== 'object') return []
    const item = entry as Record<string, unknown>
    const evidenceFrames: EvidenceFrame[] = Array.isArray(item.evidence_frames)
      ? item.evidence_frames.flatMap((frame) => {
          if (!frame || typeof frame !== 'object') return []
          const record = frame as Record<string, unknown>
          if (typeof record.image_base64 !== 'string') return []
          return [{
            timestamp_sec: typeof record.timestamp_sec === 'number' && Number.isFinite(record.timestamp_sec) ? record.timestamp_sec : 0,
            image_base64: record.image_base64,
          }]
        })
      : []
    const ruleValue = item.rule && typeof item.rule === 'object' ? item.rule as Record<string, unknown> : null
    return [{
      type: typeof item.type === 'string' ? item.type : 'Detected event',
      timecode_sec: typeof item.timecode_sec === 'number' && Number.isFinite(item.timecode_sec) ? Math.max(0, item.timecode_sec) : 0,
      description: typeof item.description === 'string' ? item.description : 'No description provided.',
      evidence_frames: evidenceFrames,
      rule: ruleValue ? {
        document: typeof ruleValue.document === 'string' ? ruleValue.document : undefined,
        section: typeof ruleValue.section === 'string' ? ruleValue.section : undefined,
        url: typeof ruleValue.url === 'string' ? ruleValue.url : undefined,
      } : null,
    }]
  })
}

function parseJobResponse(value: unknown): UiJobResponse {
  if (!value || typeof value !== 'object') throw new Error('The analysis status response was invalid.')
  const payload = value as Record<string, unknown>
  if (typeof payload.job_id !== 'string' || !isAnalysisStatus(payload.status)) {
    throw new Error('The analysis status response is missing required details.')
  }
  return {
    job_id: payload.job_id,
    status: payload.status,
    stage: typeof payload.stage === 'string' ? payload.stage : undefined,
    progress: typeof payload.progress === 'number' && Number.isFinite(payload.progress)
      ? Math.min(1, Math.max(0, payload.progress))
      : undefined,
    video_id: typeof payload.video_id === 'string' ? payload.video_id : undefined,
    stream_url: typeof payload.stream_url === 'string' ? payload.stream_url : undefined,
    verdict: typeof payload.verdict === 'string' ? payload.verdict : undefined,
    violations: parseViolations(payload.violations),
    error: typeof payload.error === 'string' ? payload.error : undefined,
  }
}

function responseError(response: XMLHttpRequest) {
  const detail = response.response && typeof response.response === 'object'
    ? (response.response as Record<string, unknown>).detail
    : null
  if (typeof detail === 'string') return detail
  if (response.status === 413) return 'Размер видео превышает допустимое ограничение.'
  if (response.status === 0) return 'Не удалось подключиться к сервису. Проверьте подключение и повторите попытку.'
  return `Не удалось загрузить видео (HTTP ${response.status}).`
}

export function uploadVideo(file: File, onProgress: (percent: number) => void): Promise<UiAnalyzeResponse> {
  return new Promise((resolve, reject) => {
    const request = new XMLHttpRequest()
    request.open('POST', '/ui/analyze')
    request.responseType = 'json'
    request.timeout = 10 * 60 * 1000
    request.upload.onprogress = (event) => {
      if (event.lengthComputable) onProgress(Math.min(99, Math.round((event.loaded / event.total) * 100)))
    }
    request.onload = () => {
      if (request.status < 200 || request.status >= 300) {
        reject(new Error(responseError(request)))
        return
      }
      try {
        const result = parseAnalyzeResponse(request.response)
        onProgress(100)
        resolve(result)
      } catch (error) {
        reject(error instanceof Error ? error : new Error('The upload response was invalid.'))
      }
    }
    request.onerror = () => reject(new Error('Не удалось подключиться к сервису. Проверьте подключение и повторите попытку.'))
    request.ontimeout = () => reject(new Error('Истекло время ожидания загрузки видео.'))

    const body = new FormData()
    body.append('file', file, file.name)
    request.send(body)
  })
}

export async function getJobStatus(jobId: string): Promise<UiJobResponse> {
  const response = await fetch(`/ui/jobs/${encodeURIComponent(jobId)}`, { headers: { Accept: 'application/json' } })
  if (!response.ok) {
    if (response.status === 404) throw new Error('Задание анализа не найдено.')
    throw new Error(`Не удалось получить статус анализа (HTTP ${response.status}).`)
  }
  return parseJobResponse(await response.json())
}

export function loadInvestigations(): StoredInvestigation[] {
  try {
    const stored: unknown = JSON.parse(localStorage.getItem(HISTORY_KEY) ?? '[]')
    if (!Array.isArray(stored)) return []
    return stored.filter((item): item is StoredInvestigation => {
      if (!item || typeof item !== 'object') return false
      const record = item as Record<string, unknown>
      return typeof record.videoId === 'string'
        && typeof record.jobId === 'string'
        && typeof record.fileName === 'string'
        && typeof record.size === 'number'
        && isAnalysisStatus(record.status)
    }).slice(0, 100).map((item) => ({
      videoId: item.videoId,
      jobId: item.jobId,
      fileName: item.fileName,
      size: item.size,
      durationSeconds: typeof item.durationSeconds === 'number' ? item.durationSeconds : null,
      createdAt: typeof item.createdAt === 'string' ? item.createdAt : new Date().toISOString(),
      status: item.status,
      stage: typeof item.stage === 'string' ? item.stage : '',
      progress: typeof item.progress === 'number' ? Math.min(1, Math.max(0, item.progress)) : 0,
      streamUrl: typeof item.streamUrl === 'string' ? item.streamUrl : null,
      verdict: typeof item.verdict === 'string' ? item.verdict : null,
      violationCount: typeof item.violationCount === 'number' ? item.violationCount : 0,
      error: typeof item.error === 'string' ? item.error : null,
    }))
  } catch {
    return []
  }
}

export function saveInvestigations(items: StoredInvestigation[]) {
  try {
    localStorage.setItem(HISTORY_KEY, JSON.stringify(items.slice(0, 100)))
  } catch {
    // The service keeps the video; this list remembers job IDs for this browser.
  }
}
