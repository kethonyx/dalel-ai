import { useEffect, useRef, useState, type ChangeEvent, type CSSProperties, type DragEvent, type KeyboardEvent, type ReactNode } from 'react'
import { AnimatePresence, motion, useReducedMotion } from 'motion/react'
import {
  AlertTriangle,
  ArrowUpRight,
  ArrowLeft,
  Check,
  ChevronDown,
  CircleHelp,
  CloudUpload,
  Clock3,
  FileVideo2,
  Film,
  FolderSearch,
  Fullscreen,
  Info,
  LoaderCircle,
  Minus,
  Pause,
  Play,
  RefreshCw,
  RotateCcw,
  Search,
  ShieldCheck,
  Trash2,
  Upload,
  UserRound,
  Video,
  X,
  type LucideIcon,
} from 'lucide-react'
import { getJobStatus, loadInvestigations, saveInvestigations, uploadVideo, type AnalysisStatus, type AnalysisViolation, type StoredInvestigation, type UiJobResponse } from './services/videoApi'
import { InvestigationPoster } from './components/InvestigationPoster'
import { InvestigationDetail } from './components/InvestigationDetail'
import { employees } from './employees'
import { getSavedReview, type ReviewDecision } from './hooks/useReviewStore'
import './App.css'

const MAX_FILE_SIZE = 200 * 1024 * 1024
const SAMPLE_DURATION = 94

type Section = 'video' | 'investigations' | 'employees'
type ReviewStatus = 'Awaiting review' | 'Confirmed' | 'Dismissed' | 'Inconclusive'
type SampleEvent = {
  id: string
  timestamp: number
  title: string
  category: string
  description: string
}
type Toast = { id: number; message: string } | null
type SelectedVideo = { file: File | null; url: string; name: string; size: number; isObjectUrl: boolean; source: 'local' | 'server' }
type InvestigationItem = StoredInvestigation & { file: File | null; violations: AnalysisViolation[] }
type InvestigationFilter = 'all' | 'violations' | 'clean' | 'unassigned' | 'pending'
type UploadState = { fileName: string; size: number; progress: number; phase: 'transferring' | 'processing' | 'complete'; status: AnalysisStatus; stage: string; jobId?: string; error?: string; verdict?: string | null; violationCount?: number }

const sampleEvents: SampleEvent[] = [
  {
    id: 'A',
    timestamp: 14,
    title: 'Cash-handling activity',
    category: 'Cash handling',
    description: 'Illustrative example of a cash-handling moment that a reviewer might inspect more closely.',
  },
  {
    id: 'B',
    timestamp: 37,
    title: 'Transaction-area movement',
    category: 'Transaction area',
    description: 'Illustrative movement near a transaction area. Context and the full recording would be needed for review.',
  },
  {
    id: 'C',
    timestamp: 72,
    title: 'Unusual interaction',
    category: 'Customer interaction',
    description: 'Illustrative interaction for demonstrating the review controls. This is not a real detection.',
  },
]

const navItems: { id: Section; label: string; icon: LucideIcon }[] = [
  { id: 'video', label: 'Video Analysis', icon: Video },
  { id: 'investigations', label: 'Investigations', icon: FolderSearch },
  { id: 'employees', label: 'Employees', icon: UserRound },
]

function formatTime(seconds: number) {
  const safeSeconds = Math.max(0, Math.floor(seconds))
  return `${String(Math.floor(safeSeconds / 60)).padStart(2, '0')}:${String(safeSeconds % 60).padStart(2, '0')}`
}

function formatFileSize(bytes: number) {
  if (bytes >= 1024 ** 3) return `${(bytes / 1024 ** 3).toFixed(2)} GB`
  if (bytes >= 1024 ** 2) return `${(bytes / 1024 ** 2).toFixed(1)} MB`
  if (bytes >= 1024) return `${(bytes / 1024).toFixed(0)} KB`
  return `${bytes} bytes`
}

function formatDate(value: string) {
  const date = new Date(value)
  if (Number.isNaN(date.getTime())) return 'Date unavailable'
  return new Intl.DateTimeFormat('en-GB', { dateStyle: 'medium', timeStyle: 'short' }).format(date)
}

function caseReviewStatus(item: InvestigationItem): ReviewDecision {
  if (!item.violations?.length) return 'pending'
  const review = getSavedReview(item.jobId)
  const decisions = item.violations.map((_, index) => review.eventDecisions[String(index)] ?? 'pending')
  if (decisions.every((decision) => decision === 'confirmed')) return 'confirmed'
  if (decisions.every((decision) => decision === 'dismissed')) return 'dismissed'
  return 'pending'
}

function hasViolation(item: InvestigationItem) {
  return item.verdict === 'violation' || (!item.verdict && (item.violationCount > 0 || item.violations.length > 0))
}

function caseTitle(fileName: string) {
  const name = fileName.replace(/\.[^.]+$/, '').trim()
  return name ? `Case ${name}` : 'Video investigation'
}

function applyJobStatus(item: InvestigationItem, job: UiJobResponse): InvestigationItem {
  return {
    ...item,
    status: job.status,
    stage: job.stage ?? (job.status === 'done' ? 'Analysis complete' : job.status === 'failed' ? 'Analysis failed' : item.stage),
    progress: job.progress ?? (job.status === 'done' ? 1 : item.progress),
    streamUrl: job.stream_url ?? item.streamUrl,
    verdict: job.verdict ?? (job.status === 'done' && job.violations ? (job.violations.length ? 'violation' : 'no_violation') : item.verdict),
    violationCount: job.violations?.length ?? item.violationCount,
    violations: job.violations ?? item.violations,
    error: job.error ?? null,
  }
}

function persistInvestigations(items: InvestigationItem[]) {
  saveInvestigations(items.map((item) => ({
    videoId: item.videoId,
    jobId: item.jobId,
    fileName: item.fileName,
    size: item.size,
    durationSeconds: item.durationSeconds,
    createdAt: item.createdAt,
    status: item.status,
    stage: item.stage,
    progress: item.progress,
    streamUrl: item.streamUrl,
    verdict: item.verdict,
    violationCount: item.violationCount,
    error: item.error,
  })))
}

function IconButton({
  label,
  onClick,
  children,
  className = '',
  disabled = false,
}: {
  label: string
  onClick: () => void
  children: ReactNode
  className?: string
  disabled?: boolean
}) {
  return (
    <button className={`icon-button ${className}`} type="button" aria-label={label} title={label} onClick={onClick} disabled={disabled}>
      {children}
    </button>
  )
}

function StatusBadge({ status }: { status: ReviewStatus }) {
  const className = status === 'Confirmed' ? 'confirmed' : status === 'Dismissed' ? 'dismissed' : status === 'Inconclusive' ? 'inconclusive' : 'pending'
  return <span className={`status-badge ${className}`}><i aria-hidden="true" />{status}</span>
}

function ForteLogo() {
  return (
    <a className="brand" href="#video-analysis" aria-label="ForteBank Compliance Intelligence" title="ForteBank Compliance Intelligence">
      <span className="brand-symbol" aria-hidden="true"><i /><i /><i /></span>
      <span className="brand-name">ForteBank</span>
    </a>
  )
}

function InvestigationGrid({
  items,
  loading,
  error,
  onRetry,
  onOpen,
  onRemove,
  onNewVideo,
}: {
  items: InvestigationItem[]
  loading: boolean
  error: string
  onRetry: () => void
  onOpen: (item: InvestigationItem) => void
  onRemove: (item: InvestigationItem) => void
  onNewVideo: () => void
}) {
  const reduceMotion = useReducedMotion()
  const [query, setQuery] = useState('')
  const [filter, setFilter] = useState<InvestigationFilter>('all')
  const [sortOrder, setSortOrder] = useState<'newest' | 'oldest'>('newest')
  const [reviewRevision, setReviewRevision] = useState(0)

  useEffect(() => {
    const refreshReviews = () => setReviewRevision((revision) => revision + 1)
    window.addEventListener('forte-review-saved', refreshReviews)
    return () => window.removeEventListener('forte-review-saved', refreshReviews)
  }, [])

  const filterItems: { id: InvestigationFilter; label: string }[] = [
    { id: 'all', label: 'All' },
    { id: 'violations', label: 'Violations' },
    { id: 'clean', label: 'Clean' },
    { id: 'unassigned', label: 'Unassigned' },
    { id: 'pending', label: 'Pending review' },
  ]
  const violationTotal = items.filter((item) => item.status === 'done' && hasViolation(item)).length
  const unassignedTotal = items.filter((item) => !getSavedReview(item.jobId).employeeId).length
  const visibleItems = items
    .filter((item) => item.fileName.toLowerCase().includes(query.trim().toLowerCase()))
    .filter((item) => {
      if (filter === 'violations') return item.status === 'done' && hasViolation(item)
      if (filter === 'clean') return item.status === 'done' && !hasViolation(item)
      if (filter === 'unassigned') return !getSavedReview(item.jobId).employeeId
      if (filter === 'pending') return caseReviewStatus(item) === 'pending'
      return true
    })
    .sort((a, b) => {
      const difference = new Date(a.createdAt).getTime() - new Date(b.createdAt).getTime()
      return sortOrder === 'newest' ? -difference : difference
    })

  function handleCardKeyDown(event: KeyboardEvent<HTMLElement>, item: InvestigationItem) {
    if (event.target !== event.currentTarget) return
    if (event.key === 'Enter' || event.key === ' ') {
      event.preventDefault()
      onOpen(item)
    }
  }

  return (
    <motion.section
      className="investigations-view"
      data-review-revision={reviewRevision}
      initial={reduceMotion ? false : { opacity: 0, y: 5 }}
      animate={{ opacity: 1, y: 0 }}
      exit={reduceMotion ? undefined : { opacity: 0, y: -4 }}
      transition={{ duration: 0.18, ease: 'easeOut' }}
      aria-labelledby="investigations-title"
    >
      <div className="page-heading investigations-heading">
        <div>
          <h1 id="investigations-title">Investigations</h1>
          <p>Videos sent to the backend, with live analysis status and playback.</p>
        </div>
        <button className="button-primary" type="button" onClick={onNewVideo}><CloudUpload size={15} /> Add a recording</button>
      </div>

      <div className="investigation-summary" aria-live="polite">
        <span><strong>{items.length}</strong> {items.length === 1 ? 'video' : 'videos'}</span><i />
        <span><strong>{violationTotal}</strong> {violationTotal === 1 ? 'violation' : 'violations'}</span><i />
        <span><strong>{unassignedTotal}</strong> unassigned</span>
      </div>

      <div className="investigations-toolbar">
        <label className="investigation-search"><Search size={15} /><input value={query} onChange={(event) => setQuery(event.target.value)} placeholder="Search recordings" aria-label="Search recordings" /></label>
        <label className="investigation-sort"><span>Sort</span><select value={sortOrder} onChange={(event) => setSortOrder(event.target.value as 'newest' | 'oldest')} aria-label="Sort investigations"><option value="newest">Newest</option><option value="oldest">Oldest</option></select></label>
      </div>

      <div className="investigation-filter-row" role="group" aria-label="Filter investigations">
        {filterItems.map((option) => <button key={option.id} className={`filter-chip${filter === option.id ? ' active' : ''}`} type="button" aria-pressed={filter === option.id} onClick={() => setFilter(option.id)}>{option.label}</button>)}
      </div>

      {loading ? (
        <div className="investigation-grid" aria-label="Loading investigations" aria-busy="true">
          {[0, 1, 2].map((item) => <div className="investigation-skeleton" key={item}><div /><span /><i /></div>)}
        </div>
      ) : error && items.length === 0 ? (
        <div className="investigations-state error-state" role="alert">
          <div className="investigations-state-icon"><AlertTriangle size={19} /></div>
          <h2>Could not load recordings</h2>
          <p>{error}</p>
          <button className="button-secondary" type="button" onClick={onRetry}><RefreshCw size={14} /> Try again</button>
        </div>
      ) : items.length === 0 ? (
        <div className="investigations-state empty-state">
          <div className="empty-illustration" aria-hidden="true">
            <div className="empty-orbit orbit-one" /><div className="empty-orbit orbit-two" />
            <div className="empty-file-icon"><FileVideo2 size={24} strokeWidth={1.5} /></div>
            <span className="empty-spark spark-one" /><span className="empty-spark spark-two" />
          </div>
          <span className="micro-label">YOUR RECORDING LIBRARY</span>
          <h2>No recordings yet</h2>
          <p>Upload a .mov, .mp4, or .m4v recording to start a case.</p>
          <button className="button-primary" type="button" onClick={onNewVideo}><CloudUpload size={15} /> Start with a video</button>
        </div>
      ) : visibleItems.length === 0 ? (
        <div className="investigations-state filtered-empty-state">
          <div className="placeholder-icon"><Search size={19} /></div>
          <h2>No matching investigations</h2>
          <p>Try another search or clear the selected filter.</p>
          <div className="filtered-empty-actions"><button className="button-secondary" type="button" onClick={() => { setQuery(''); setFilter('all') }}>Clear filters</button><button className="button-primary" type="button" onClick={onNewVideo}><CloudUpload size={14} /> Add a recording</button></div>
        </div>
      ) : (
        <>
          {error && <div className="list-refresh-error" role="status"><AlertTriangle size={13} /><span>Showing available recordings. Some job statuses could not be refreshed.</span><button type="button" onClick={onRetry}>Retry</button></div>}
          <div className="investigation-grid">
            {visibleItems.map((item) => {
              const violation = hasViolation(item)
              const reviewStatus = caseReviewStatus(item)
              const employee = employees.find((entry) => entry.id === getSavedReview(item.jobId).employeeId)
              const statusLabel = item.status === 'processing' ? 'Processing' : item.status === 'failed' ? 'Failed' : 'Done'
              return <motion.article
                key={item.jobId}
                className={`investigation-card${item.status === 'failed' ? ' failed-card' : ''}${item.status === 'done' && violation ? ' violation-card' : ''}`}
                onClick={() => onOpen(item)}
                onKeyDown={(event) => handleCardKeyDown(event, item)}
                whileHover={reduceMotion ? undefined : { y: -2 }}
                transition={{ duration: 0.16, ease: 'easeOut' }}
                aria-label={`Open ${item.fileName}`}
                role="button"
                tabIndex={0}
              >
                <div className="investigation-card-art">
                  <div className="card-art-grid" />
                  <span className="card-art-corner corner-one" /><span className="card-art-corner corner-two" />
                  <span className="card-art-corner corner-three" /><span className="card-art-corner corner-four" />
                  <InvestigationPoster
                    jobId={item.jobId}
                    source={item.streamUrl ?? ''}
                    file={item.file}
                    evidenceFrame={violation ? item.violations[0]?.evidence_frames[0]?.image_base64 : undefined}
                    fallback={<span className="record-film-icon"><Film size={20} strokeWidth={1.5} /></span>}
                  />
                  <span className={`record-status-chip ${item.status}${item.status === 'done' ? ' done' : ''}${item.status === 'failed' ? ' failed' : ''}`}><i />{statusLabel}</span>
                  {item.durationSeconds !== null && <span className="record-duration-chip">{formatTime(item.durationSeconds)}</span>}
                </div>
                <span className="investigation-card-body">
                  <span className="investigation-case-title">{caseTitle(item.fileName)}</span>
                  <span className="investigation-file-name" title={item.fileName}>{item.fileName}</span>
                  {item.status === 'done' && <span className={`verdict-pill card-verdict ${violation ? 'violation' : 'clean'}`}><i />{violation ? `Violation detected · ${item.violationCount || item.violations.length} ${item.violationCount === 1 || item.violations.length === 1 ? 'event' : 'events'}` : 'No violation'}</span>}
                  <span className="case-card-badges"><span className="employee-chip"><UserRound size={12} />{employee?.name ?? 'Unassigned'}</span><span className={`review-pill ${reviewStatus}`}>{reviewStatus === 'confirmed' ? 'Confirmed' : reviewStatus === 'dismissed' ? 'Dismissed' : 'Pending review'}</span></span>
                  <span className="investigation-meta"><span>{formatFileSize(item.size)}</span><i />{formatDate(item.createdAt)}</span>
                  {item.status === 'processing' && <span className="case-processing-track"><i style={{ width: `${Math.round(item.progress * 100)}%` }} /></span>}
                  {item.status === 'failed' && <span className="investigation-stage failed-stage" title={item.error ?? undefined}>{item.error || 'Analysis failed'}</span>}
                  <span className="investigation-card-footer">Open case <ArrowUpRight size={13} /></span>
                  {item.status === 'failed' && <button className="failed-case-remove" type="button" title="Remove this case from this browser; backend storage is unchanged" aria-label={`Remove ${item.fileName} from this browser`} onClick={(event) => { event.stopPropagation(); onRemove(item) }}><Trash2 size={13} /></button>}
                </span>
              </motion.article>
            })}
          </div>
        </>
      )}
    </motion.section>
  )
}

function App() {
  const reduceMotion = useReducedMotion()
  const fileInputRef = useRef<HTMLInputElement>(null)
  const videoRef = useRef<HTMLVideoElement>(null)
  const toastIdRef = useRef(0)
  const sampleTimeRef = useRef(0)
  const [section, setSection] = useState<Section>('video')
  const [fileSelection, setFileSelection] = useState<SelectedVideo | null>(null)
  const [fileDuration, setFileDuration] = useState<number | null>(null)
  const [fileError, setFileError] = useState('')
  const [dragging, setDragging] = useState(false)
  const [sampleMode, setSampleMode] = useState(false)
  const [selectedEventId, setSelectedEventId] = useState(sampleEvents[0].id)
  const [sampleStatuses, setSampleStatuses] = useState<Record<string, ReviewStatus>>({})
  const [sampleTime, setSampleTime] = useState(0)
  const [samplePlaying, setSamplePlaying] = useState(false)
  const [toast, setToast] = useState<Toast>(null)
  const [investigations, setInvestigations] = useState<InvestigationItem[]>(() => loadInvestigations().map((item) => ({ ...item, file: null, violations: [] })))
  const investigationsRef = useRef(investigations)
  const [investigationsLoading, setInvestigationsLoading] = useState(false)
  const [investigationsError, setInvestigationsError] = useState('')
  const [investigationsRevision, setInvestigationsRevision] = useState(0)
  const [uploadState, setUploadState] = useState<UploadState | null>(null)
  const [selectedInvestigation, setSelectedInvestigation] = useState<InvestigationItem | null>(null)
  const [backendOnline, setBackendOnline] = useState(false)

  const file = fileSelection?.file ?? null
  const fileUrl = fileSelection?.url ?? ''

  useEffect(() => {
    if (!fileSelection?.isObjectUrl) return
    const objectUrl = fileSelection.url
    return () => URL.revokeObjectURL(objectUrl)
  }, [fileSelection])

  useEffect(() => {
    investigationsRef.current = investigations
  }, [investigations])

  useEffect(() => {
    let cancelled = false
    async function checkBackend() {
      try {
        const response = await fetch('/health', { headers: { Accept: 'application/json' } })
        if (!cancelled) setBackendOnline(response.ok)
      } catch {
        if (!cancelled) setBackendOnline(false)
      }
    }
    void checkBackend()
    const interval = window.setInterval(() => void checkBackend(), 20000)
    return () => {
      cancelled = true
      window.clearInterval(interval)
    }
  }, [])

  useEffect(() => {
    if (section !== 'investigations' || investigationsRef.current.length === 0) return
    let cancelled = false
    let timer: number | undefined
    async function refreshStatuses() {
      const current = investigationsRef.current
      let refreshError = ''
      const nextByJob = new Map<string, InvestigationItem>()
      await Promise.all(current.map(async (item) => {
        try {
          nextByJob.set(item.jobId, applyJobStatus(item, await getJobStatus(item.jobId)))
        } catch (error) {
          refreshError = error instanceof Error ? error.message : 'Could not refresh analysis status.'
          nextByJob.set(item.jobId, item)
        }
      }))
      if (cancelled) return
      const next = investigationsRef.current.map((item) => nextByJob.get(item.jobId) ?? item)
      investigationsRef.current = next
      setInvestigations(next)
      persistInvestigations(next)
      setInvestigationsError(refreshError)
      setInvestigationsLoading(false)
      if (!refreshError && next.some((item) => item.status === 'processing')) {
        timer = window.setTimeout(() => void refreshStatuses(), 1500)
      }
    }
    void refreshStatuses()
    return () => {
      cancelled = true
      if (timer !== undefined) window.clearTimeout(timer)
    }
  }, [section, investigationsRevision])

  useEffect(() => {
    if (!toast) return
    const timeout = window.setTimeout(() => setToast(null), 3200)
    return () => window.clearTimeout(timeout)
  }, [toast])

  useEffect(() => {
    if (!sampleMode || !samplePlaying) return
    const interval = window.setInterval(() => {
      const next = Math.min(SAMPLE_DURATION, sampleTimeRef.current + 0.5)
      sampleTimeRef.current = next
      setSampleTime(next)
      if (next >= SAMPLE_DURATION) setSamplePlaying(false)
    }, 500)
    return () => window.clearInterval(interval)
  }, [sampleMode, samplePlaying])

  useEffect(() => {
    sampleTimeRef.current = sampleTime
  }, [sampleTime])

  const selectedEvent = sampleEvents.find((event) => event.id === selectedEventId) ?? sampleEvents[0]
  const selectedStatus = sampleStatuses[selectedEvent.id] ?? 'Awaiting review'
  const reviewedCount = Object.values(sampleStatuses).filter((status) => status !== 'Awaiting review').length
  const previewFailed = fileError.startsWith('This video could not be previewed') || fileError.startsWith('This stored video does not have a playback URL')
  const pageTitle = section === 'video' ? 'Video Analysis' : section === 'investigations' ? 'Investigations' : 'Employees'
  const uploadStepIndex = uploadState?.phase === 'complete'
    ? uploadState.status === 'done' ? 3 : 2
    : uploadState?.phase === 'transferring'
      ? 0
      : uploadState?.status === 'processing' && /queue|очеред/i.test(uploadState.stage)
        ? 1
        : 2
  const uploadSteps = ['Upload video', 'Queue analysis', 'Analyze recording']

  function showToast(message: string) {
    toastIdRef.current += 1
    setToast({ id: toastIdRef.current, message })
  }

  function navigateToSection(nextSection: Section) {
    if (nextSection === 'investigations' && investigationsRef.current.length > 0) {
      setInvestigationsLoading(true)
      setInvestigationsError('')
      if (section === 'investigations') setInvestigationsRevision((current) => current + 1)
    }
    setSection(nextSection)
  }

  function retryInvestigations() {
    setInvestigationsLoading(true)
    setInvestigationsError('')
    setInvestigationsRevision((current) => current + 1)
  }

  function handleFile(candidate?: File) {
    if (!candidate) return
    if (!/\.(mov|mp4|m4v)$/i.test(candidate.name)) {
      setFileError('Этот формат не поддерживается. Выберите .mov, .mp4 или .m4v.')
      return
    }
    if (candidate.size > MAX_FILE_SIZE) {
      setFileError('Размер файла превышает лимит backend — 200 МБ.')
      return
    }
    setFileError('')
    setFileSelection({ file: candidate, url: URL.createObjectURL(candidate), name: candidate.name, size: candidate.size, isObjectUrl: true, source: 'local' })
    setFileDuration(null)
    showToast('Файл выбран · загрузка начнётся после подтверждения')
  }

  function handleFileChange(event: ChangeEvent<HTMLInputElement>) {
    handleFile(event.target.files?.[0])
    event.target.value = ''
  }

  function handleDragOver(event: DragEvent<HTMLDivElement>) {
    event.preventDefault()
    setDragging(true)
  }

  function handleDragLeave(event: DragEvent<HTMLDivElement>) {
    if (!event.currentTarget.contains(event.relatedTarget as Node | null)) setDragging(false)
  }

  function handleDrop(event: DragEvent<HTMLDivElement>) {
    event.preventDefault()
    setDragging(false)
    handleFile(event.dataTransfer.files[0])
  }

  function removeFile() {
    setFileSelection(null)
    setFileError('')
    setFileDuration(null)
    showToast('Selected file removed')
  }

  function upsertInvestigation(item: InvestigationItem) {
    const next = [item, ...investigationsRef.current.filter((current) => current.jobId !== item.jobId)]
    investigationsRef.current = next
    setInvestigations(next)
    persistInvestigations(next)
  }

  async function startUpload() {
    if (!file || uploadState) return
    const currentFile = file
    const currentDuration = fileDuration
    setFileError('')
    setUploadState({ fileName: currentFile.name, size: currentFile.size, progress: 0, phase: 'transferring', status: 'processing', stage: 'Uploading video' })

    try {
      const accepted = await uploadVideo(currentFile, (progress) => {
        setUploadState((current) => current?.phase === 'transferring' ? { ...current, progress } : current)
      })
      let item: InvestigationItem = {
        videoId: accepted.video_id,
        jobId: accepted.job_id,
        fileName: currentFile.name,
        size: currentFile.size,
        durationSeconds: currentDuration,
        createdAt: new Date().toISOString(),
        status: accepted.status,
        stage: 'В очереди',
        progress: 0,
        streamUrl: null,
        verdict: null,
        violationCount: 0,
        error: null,
        file: currentFile,
        violations: [],
      }
      upsertInvestigation(item)
      setUploadState({ fileName: item.fileName, size: item.size, progress: item.progress * 100, phase: 'processing', status: 'processing', stage: item.stage, jobId: item.jobId })

      let job: UiJobResponse | null = null
      let statusError = ''
      let consecutiveErrors = 0
      while (!job || job.status === 'processing') {
        try {
          job = await getJobStatus(item.jobId)
          consecutiveErrors = 0
        } catch (error) {
          consecutiveErrors += 1
          statusError = error instanceof Error ? error.message : 'Could not refresh analysis status.'
          if (consecutiveErrors >= 4) break
          await new Promise((resolve) => window.setTimeout(resolve, 1200))
          continue
        }

        item = applyJobStatus(item, job)
        upsertInvestigation(item)
        setUploadState({
          fileName: item.fileName,
          size: item.size,
          progress: item.progress * 100,
          phase: job.status === 'processing' ? 'processing' : 'complete',
          status: job.status,
          stage: item.stage,
          jobId: item.jobId,
          error: item.error ?? undefined,
          verdict: item.verdict,
          violationCount: item.violationCount,
        })
        if (job.status !== 'processing') break
        await new Promise((resolve) => window.setTimeout(resolve, 1500))
      }

      if (statusError && consecutiveErrors >= 4) {
        setUploadState({ fileName: item.fileName, size: item.size, progress: item.progress * 100, phase: 'complete', status: 'processing', stage: 'Status temporarily unavailable', jobId: item.jobId, error: statusError })
        showToast('Video uploaded · analysis status will refresh in Investigations')
      } else if (job?.status === 'failed') {
        showToast('Video stored · backend analysis failed')
      } else {
        showToast('Video uploaded · analysis finished')
      }
    } catch (error) {
      const message = error instanceof Error ? error.message : 'The video could not be uploaded.'
      setUploadState(null)
      setFileError(message)
      showToast('Upload failed · see the message below the preview')
    }
  }

  function finishUploadFlow(openInvestigations = true) {
    if (uploadState?.phase !== 'complete') return
    setUploadState(null)
    setFileSelection(null)
    setFileDuration(null)
    setSampleMode(false)
    if (openInvestigations) navigateToSection('investigations')
  }

  async function openInvestigation(item: InvestigationItem) {
    let current = item
    try {
      current = applyJobStatus(item, await getJobStatus(item.jobId))
      upsertInvestigation(current)
    } catch {
      showToast('Could not refresh backend status · opening the saved entry')
    }
    setSelectedInvestigation(current)
  }

  function removeInvestigation(item: InvestigationItem) {
    const next = investigationsRef.current.filter((candidate) => candidate.jobId !== item.jobId)
    investigationsRef.current = next
    setInvestigations(next)
    persistInvestigations(next)
    showToast('Case removed from this browser · backend copy remains stored')
  }

  function openSample() {
    setSection('video')
    setSampleMode(true)
    setSamplePlaying(false)
    setSampleTime(0)
    setSelectedEventId(sampleEvents[0].id)
  }

  function resetSample() {
    setSampleStatuses({})
    setSelectedEventId(sampleEvents[0].id)
    setSampleTime(0)
    setSamplePlaying(false)
    showToast('Sample mode reset')
  }

  function selectEvent(event: SampleEvent) {
    setSelectedEventId(event.id)
    setSampleTime(event.timestamp)
    setSamplePlaying(false)
  }

  function decideEvent(status: Exclude<ReviewStatus, 'Awaiting review'>) {
    setSampleStatuses((current) => ({ ...current, [selectedEvent.id]: status }))
    showToast(`Sample event ${selectedEvent.id} marked ${status.toLowerCase()}`)
  }

  function toggleSamplePlayback() {
    if (sampleTime >= SAMPLE_DURATION) setSampleTime(0)
    setSamplePlaying((playing) => !playing)
  }

  function toggleFullscreen() {
    const player = document.querySelector('.sample-player')
    if (!player) return
    if (document.fullscreenElement) void document.exitFullscreen()
    else if (player instanceof HTMLElement) void player.requestFullscreen?.()
  }

  return (
    <div className="app-shell">
      <aside className="sidebar">
        <ForteLogo />
        <div className="workspace-switcher">
          <div className="workspace-mark"><ShieldCheck size={15} strokeWidth={1.8} /></div>
          <div className="workspace-switcher-copy"><span>Compliance</span><small>Operations</small></div>
          <ChevronDown size={14} className="switcher-chevron" aria-hidden="true" />
        </div>

        <nav className="primary-nav" aria-label="Main navigation">
          <div className="nav-label">Workspace</div>
          {navItems.map(({ id, label, icon: Icon }) => (
            <button
              key={id}
              type="button"
              className={`nav-item${section === id ? ' active' : ''}`}
              onClick={() => { navigateToSection(id); setSampleMode(false); setSamplePlaying(false) }}
              aria-current={section === id ? 'page' : undefined}
            >
              <Icon size={16} strokeWidth={1.8} aria-hidden="true" />
              <span>{label}</span>
              {id === 'employees' && <span className="nav-soon">Soon</span>}
            </button>
          ))}
        </nav>

        <div className="sidebar-foot" title="FastAPI connection through the local Vite development proxy">
          <span className={`status-dot${backendOnline ? ' is-configured' : ' is-offline'}`} aria-hidden="true" />
          <div><strong>Connection</strong><span>{backendOnline ? 'Connected' : 'Offline'}</span></div>
          <CircleHelp size={15} aria-hidden="true" />
        </div>
      </aside>

      <div className="main-column">
        <header className="topbar">
          <div className="breadcrumb"><span>Compliance Intelligence</span><span className="breadcrumb-separator">/</span><strong>{pageTitle}</strong></div>
          <div className={`environment-label${backendOnline ? ' is-online' : ' is-offline'}`} title="FastAPI connection through the local Vite development proxy"><span className="environment-dot" />{backendOnline ? 'Connected' : 'Offline'}</div>
        </header>

        <main className={`page-content${sampleMode ? ' sample-page' : ''}`} id="video-analysis">
          <AnimatePresence mode="wait" initial={false}>
            {section === 'investigations' ? (
              <InvestigationGrid
                key="investigations"
                items={investigations}
                loading={investigationsLoading}
                error={investigationsError}
                onRetry={retryInvestigations}
                onOpen={openInvestigation}
                onRemove={removeInvestigation}
                onNewVideo={() => navigateToSection('video')}
              />
            ) : section === 'employees' ? (
              <motion.section
                key="employees"
                className="coming-soon-view"
                initial={reduceMotion ? false : { opacity: 0, y: 5 }}
                animate={{ opacity: 1, y: 0 }}
                exit={reduceMotion ? undefined : { opacity: 0, y: -4 }}
                transition={{ duration: 0.18, ease: 'easeOut' }}
              >
                <div className="placeholder-icon"><UserRound size={20} /></div>
                <span className="micro-label">WORKSPACE / IN DEVELOPMENT</span>
                <h1>{pageTitle}</h1>
                <p>This area is reserved for a future prototype stage.</p>
                <button className="button-secondary" type="button" onClick={() => setSection('video')}><ArrowLeft size={15} /> Back to Video Analysis</button>
              </motion.section>
            ) : (
              <motion.div
                key={sampleMode ? 'sample' : fileSelection ? 'file' : 'intake'}
                className="video-page"
                initial={reduceMotion ? false : { opacity: 0, y: 6 }}
                animate={{ opacity: 1, y: 0 }}
                exit={reduceMotion ? undefined : { opacity: 0, y: -4 }}
                transition={{ duration: 0.2, ease: 'easeOut' }}
              >
                <div className="page-heading">
                  <div>
                    <h1>Video Analysis</h1>
                    <p>Review teller-operation recordings and inspect potentially irregular events.</p>
                  </div>
                  {sampleMode ? (
                    <div className="heading-actions">
                      <span className="sample-chip"><i /> Sample data</span>
                      <button className="button-secondary reset-button" type="button" onClick={resetSample}><RotateCcw size={14} /> Reset sample</button>
                    </div>
                  ) : (
                    <button className="button-secondary sample-link" type="button" onClick={openSample}><Film size={15} /> Explore sample analysis</button>
                  )}
                </div>

                <AnimatePresence mode="wait" initial={false}>
                  {sampleMode ? (
                    <motion.section
                      key="sample-workspace"
                      className="review-workspace"
                      aria-label="Sample analysis review workspace"
                      initial={reduceMotion ? false : { opacity: 0, y: 5 }}
                      animate={{ opacity: 1, y: 0 }}
                      exit={reduceMotion ? undefined : { opacity: 0, y: -3 }}
                      transition={{ duration: 0.2, ease: 'easeOut' }}
                    >
                      <section className="event-pane" aria-labelledby="events-title">
                        <div className="pane-header">
                          <div><h2 id="events-title">Events</h2><span className="pane-subtitle">Illustrative review queue</span></div>
                          <span className="count-label">{sampleEvents.length.toString().padStart(2, '0')}</span>
                        </div>
                        <div className="event-list" role="list">
                          {sampleEvents.map((event, index) => {
                            const status = sampleStatuses[event.id] ?? 'Awaiting review'
                            const reviewClass = status === 'Awaiting review' ? `priority-${event.id.toLowerCase()}` : `reviewed-priority-${status.toLowerCase()}`
                            return (
                              <motion.button
                                key={event.id}
                                type="button"
                                role="listitem"
                                className={`event-row${selectedEventId === event.id ? ' selected' : ''}`}
                                onClick={() => selectEvent(event)}
                                initial={reduceMotion ? false : { opacity: 0, y: 4 }}
                                animate={{ opacity: 1, y: 0 }}
                                transition={{ duration: 0.16, delay: reduceMotion ? 0 : index * 0.025, ease: 'easeOut' }}
                                aria-pressed={selectedEventId === event.id}
                              >
                                <span className={`event-marker marker-${event.id.toLowerCase()}`}><span>{event.id}</span></span>
                                <span className="event-row-copy">
                                  <span className="event-row-top"><time>{formatTime(event.timestamp)}</time><span className={`event-priority ${reviewClass}`}><i />{status === 'Awaiting review' ? 'Review' : status}</span></span>
                                  <strong>{event.title}</strong>
                                  <small>{event.category}</small>
                                </span>
                                {status !== 'Awaiting review' && <Check className="event-reviewed-check" size={14} aria-label={status} />}
                              </motion.button>
                            )
                          })}
                        </div>
                        <div className="event-pane-foot"><Info size={14} /><span>Examples only · no real findings</span></div>
                      </section>

                      <section className="player-pane" aria-labelledby="recording-title">
                        <div className="pane-header recording-header">
                          <div className="recording-title-wrap"><span className="recording-icon"><FileVideo2 size={15} /></span><div><h2 id="recording-title">Sample recording 001</h2><span className="pane-subtitle">Illustrative timeline · 01:34</span></div></div>
                          <span className="sample-chip compact"><i /> DEMO</span>
                        </div>

                        <div className="sample-player" aria-label="Illustrative sample video placeholder">
                          <div className="schematic-frame" aria-hidden="true">
                            <span className="frame-corner corner-tl" /><span className="frame-corner corner-tr" />
                            <span className="frame-corner corner-bl" /><span className="frame-corner corner-br" />
                            <div className="schematic-topline"><span>ILLUSTRATIVE FRAME</span><span>NO FOOTAGE ATTACHED</span></div>
                            <svg className="scene-schematic" viewBox="0 0 720 300" role="presentation">
                              <path d="M38 54h644M38 246h644M72 76v147m576-147v147" />
                              <path d="M108 91h504v62H108zM108 177h197v42H108zM415 177h197v42H415z" />
                              <path d="M335 91v62m50-62v62M305 177h110m-55-24v24" />
                              <path d="M122 108h156m-156 14h102m215-14h102m-102 14h78" />
                              <circle cx="360" cy="204" r="8" /><circle cx="201" cy="198" r="5" /><circle cx="519" cy="198" r="5" />
                              <path d="M360 55v19m-3-8h6M54 150h18m-8-3v6m590-3h18m-8-3v6" />
                            </svg>
                            <div className="schematic-caption"><span>REVIEW EXAMPLE</span><strong>No sample video included</strong></div>
                          </div>
                          <div className="player-overlay-label"><span>Sample mode</span><span className="tabular">{formatTime(sampleTime)} / {formatTime(SAMPLE_DURATION)}</span></div>
                        </div>

                        <div className="timeline-controls">
                          <div className="playback-row">
                            <IconButton label={samplePlaying ? 'Pause sample timeline' : 'Play sample timeline'} onClick={toggleSamplePlayback} className="play-button">
                              {samplePlaying ? <Pause size={15} fill="currentColor" /> : <Play size={15} fill="currentColor" />}
                            </IconButton>
                            <span className="timecode"><strong>{formatTime(sampleTime)}</strong><span>/</span>{formatTime(SAMPLE_DURATION)}</span>
                            <div className="playback-spacer" />
                            <span className="timeline-speed">1×</span>
                            <IconButton label="Fullscreen placeholder" onClick={toggleFullscreen}><Fullscreen size={15} /></IconButton>
                          </div>
                          <div className="timeline-track-wrap">
                            <div className="timeline-marker-layer" aria-label="Sample event markers">
                              {sampleEvents.map((event) => (
                                <button
                                  key={event.id}
                                  className={`timeline-marker marker-${event.id.toLowerCase()}${selectedEventId === event.id ? ' active' : ''}`}
                                  style={{ left: `${(event.timestamp / SAMPLE_DURATION) * 100}%` }}
                                  type="button"
                                  aria-label={`Select sample event ${event.id} at ${formatTime(event.timestamp)}`}
                                  title={`Event ${event.id} · ${formatTime(event.timestamp)}`}
                                  onClick={() => selectEvent(event)}
                                ><span>{event.id}</span></button>
                              ))}
                            </div>
                            <input
                              className="timeline-range"
                              type="range"
                              min="0"
                              max={SAMPLE_DURATION}
                              step="0.5"
                              value={sampleTime}
                              onChange={(event) => setSampleTime(Number(event.target.value))}
                              aria-label="Seek sample timeline"
                              style={{ '--progress': `${(sampleTime / SAMPLE_DURATION) * 100}%` } as CSSProperties}
                            />
                          </div>
                          <div className="timeline-axis"><span>00:00</span><span>00:30</span><span>01:00</span><span>01:34</span></div>
                        </div>
                        <div className="sample-footnote"><Info size={13} /><span>Simulated playback controls; timestamps are illustrative and do not map to footage.</span></div>
                      </section>

                      <section className="details-pane" aria-labelledby="event-details-title">
                        <div className="pane-header details-header">
                          <div><h2 id="event-details-title">Event details</h2><span className="pane-subtitle">Human review required</span></div>
                          <span className="event-id">SAMPLE {selectedEvent.id}</span>
                        </div>
                        <AnimatePresence mode="wait" initial={false}>
                          <motion.div
                            className="event-details-body"
                            key={selectedEvent.id}
                            initial={reduceMotion ? false : { opacity: 0, y: 4 }}
                            animate={{ opacity: 1, y: 0 }}
                            exit={reduceMotion ? undefined : { opacity: 0, y: -3 }}
                            transition={{ duration: 0.16, ease: 'easeOut' }}
                          >
                            <StatusBadge status={selectedStatus} />
                            <h3>{selectedEvent.title}</h3>
                            <p className="details-description">{selectedEvent.description}</p>
                            <dl className="event-metadata">
                              <div><dt>Timestamp</dt><dd className="tabular">{formatTime(selectedEvent.timestamp)}</dd></div>
                              <div><dt>Category</dt><dd>{selectedEvent.category}</dd></div>
                              <div><dt>Review status</dt><dd><StatusBadge status={selectedStatus} /></dd></div>
                            </dl>
                            <div className="review-note"><ShieldCheck size={14} /><p>A visual cue is not a confirmed violation. Use the recording and applicable guidance to assess context.</p></div>
                            <div className="decision-label">REVIEW DECISION</div>
                            <div className="decision-actions">
                              <button type="button" className="decision-button confirm" onClick={() => decideEvent('Confirmed')}><Check size={14} /> Confirm finding</button>
                              <button type="button" className="decision-button dismiss" onClick={() => decideEvent('Dismissed')}><X size={14} /> Dismiss finding</button>
                              <button type="button" className="decision-button inconclusive" onClick={() => decideEvent('Inconclusive')}><Minus size={14} /> Mark inconclusive</button>
                            </div>
                            <p className="local-only-note">Decisions are saved in this page only.</p>
                          </motion.div>
                        </AnimatePresence>
                        <div className="review-progress">
                          <div><span>Reviewed in this demo</span><strong>{reviewedCount} / {sampleEvents.length}</strong></div>
                          <div className="review-progress-track"><i style={{ width: `${(reviewedCount / sampleEvents.length) * 100}%` }} /></div>
                        </div>
                      </section>
                    </motion.section>
                  ) : (
                    <motion.section
                      key={fileSelection ? 'selected-file' : 'upload-intake'}
                      className="intake-layout"
                      initial={reduceMotion ? false : { opacity: 0, y: 4 }}
                      animate={{ opacity: 1, y: 0 }}
                      exit={reduceMotion ? undefined : { opacity: 0, y: -3 }}
                      transition={{ duration: 0.18, ease: 'easeOut' }}
                    >
                      <section className={`intake-panel${fileSelection ? ' has-file' : ''}`} aria-label={fileSelection ? 'Selected video' : 'Video upload'}>
                        <input ref={fileInputRef} className="visually-hidden" type="file" accept=".mov,.mp4,.m4v,video/quicktime,video/mp4" onChange={handleFileChange} aria-label="Choose a video recording" />
                        {fileSelection ? (
                          <>
                            <div className="intake-panel-heading">
                              <div><span className="micro-label">{fileSelection.source === 'server' ? 'SAVED RECORDING' : 'LOCAL RECORDING'}</span><h2>{fileSelection.source === 'server' ? 'Investigation video' : 'Selected video'}</h2></div>
                              <div className="file-actions">
                                {file && <button className="button-secondary compact-button" type="button" onClick={() => fileInputRef.current?.click()}><Upload size={14} /> Replace</button>}
                                <IconButton label="Remove selected video" onClick={removeFile}><X size={16} /></IconButton>
                              </div>
                            </div>
                            <div className="video-preview-wrap">
                              {fileUrl && !previewFailed && <video ref={videoRef} className="local-video" src={fileUrl} controls playsInline onLoadedMetadata={(event) => setFileDuration(event.currentTarget.duration)} onError={() => setFileError('This video could not be previewed by the browser. The backend may still be able to analyze it.')} />}
                              {previewFailed && <div className="video-unavailable"><AlertTriangle size={18} /><span>{fileSelection.source === 'server' && !fileUrl ? 'Preview link unavailable' : 'Video preview unavailable'}</span></div>}
                              {!fileUrl && !previewFailed && <div className="video-unavailable"><AlertTriangle size={18} /><span>Preparing local preview…</span></div>}
                            </div>
                            <div className="selected-file-meta">
                              <div className="selected-file-name"><span className="file-type-icon"><FileVideo2 size={17} /></span><div><strong title={fileSelection.name}>{fileSelection.name}</strong><span>{formatFileSize(fileSelection.size)} <i /> {fileSelection.name.split('.').pop()?.toUpperCase() ?? 'VIDEO'}</span></div></div>
                              <div className="duration-meta"><Clock3 size={14} /><span>{fileDuration === null ? 'Duration unavailable' : formatTime(fileDuration)}</span></div>
                            </div>
                            {fileError && <p className="inline-file-error" role="alert"><AlertTriangle size={14} />{fileError}</p>}
                            <div className={`prototype-message${fileSelection.source === 'server' ? ' stored-message' : ''}`}><Info size={15} /><span>{fileSelection.source === 'server' ? 'Stored by the backend. Analysis status and a fresh playback link load from the job endpoint.' : 'The file stays in your browser until upload. The backend stores it and queues analysis.'}</span></div>
                            {file && <div className="upload-action-row"><button className="button-primary upload-video-button" type="button" onClick={startUpload} disabled={uploadState !== null}><CloudUpload size={15} /> Upload &amp; analyze</button><span>Stored and analyzed by backend</span></div>}
                          </>
                        ) : (
                          <>
                            <div className="intake-panel-heading">
                              <div><span className="micro-label">NEW REVIEW</span><h2>Start a video review</h2><p>Choose a teller-operation recording to inspect.</p></div>
                              <span className="intake-step">01 <i>/ 03</i></span>
                            </div>
                            <div
                              className={`drop-target${dragging ? ' is-dragging' : ''}${fileError ? ' has-error' : ''}`}
                              onDragOver={handleDragOver}
                              onDragLeave={handleDragLeave}
                              onDrop={handleDrop}
                            >
                              <div className="drop-target-content">
                                <div className="upload-glyph"><Upload size={19} strokeWidth={1.7} /></div>
                                <h3>{dragging ? 'Release to add recording' : 'Drop a recording here'}</h3>
                                <p>Drag a .mov, .mp4, or .m4v file here, or choose one from your device.</p>
                                <button className="button-primary" type="button" onClick={() => fileInputRef.current?.click()}><Upload size={15} /> Choose video</button>
                                <div className="upload-specs"><span>MOV · MP4 · M4V</span><i /><span>Up to 200 MB</span><i /><span>Backend analysis</span></div>
                              </div>
                              <div className="drop-corner drop-corner-tl" /><div className="drop-corner drop-corner-tr" /><div className="drop-corner drop-corner-bl" /><div className="drop-corner drop-corner-br" />
                            </div>
                            {fileError && <p className="upload-error" role="alert"><AlertTriangle size={14} />{fileError}</p>}
                            <div className="intake-privacy"><ShieldCheck size={15} /><span>Nothing is sent until you choose Upload &amp; analyze.</span></div>
                          </>
                        )}
                      </section>

                      <aside className="intake-aside">
                        <section className="guide-section">
                          <span className="micro-label">REVIEW WORKFLOW</span>
                          <h2>A considered review, from intake to decision.</h2>
                          <ol className="workflow-list">
                            <li className="current"><span className="workflow-number">01</span><div><strong>Select a recording</strong><p>Choose a supported video up to 200 MB.</p></div></li>
                            <li><span className="workflow-number">02</span><div><strong>Upload and analyze</strong><p>The backend stores the original and reports job progress.</p></div></li>
                            <li><span className="workflow-number">03</span><div><strong>Review the result</strong><p>Open the stored video from Investigations.</p></div></li>
                          </ol>
                        </section>
                        <section className="requirements-section">
                          <div className="requirements-heading"><h3>Recording requirements</h3><Info size={14} aria-hidden="true" /></div>
                          <dl><div><dt>Format</dt><dd>.mov · .mp4 · .m4v</dd></div><div><dt>Maximum size</dt><dd>200 MB</dd></div><div><dt>Storage</dt><dd>Backend + PostgreSQL</dd></div></dl>
                        </section>
                        <div className="prototype-callout"><span className="callout-mark"><Info size={14} /></span><p><strong>Analysis pipeline</strong><br />The interface shows the status returned by the backend.</p></div>
                      </aside>
                    </motion.section>
                  )}
                </AnimatePresence>
              </motion.div>
            )}
          </AnimatePresence>
        </main>
      </div>

      {selectedInvestigation && <InvestigationDetail key={selectedInvestigation.jobId} item={selectedInvestigation} onClose={() => setSelectedInvestigation(null)} />}

      <AnimatePresence>
        {uploadState && (
          <motion.div
            className="upload-overlay"
            initial={reduceMotion ? false : { opacity: 0 }}
            animate={{ opacity: 1 }}
            exit={reduceMotion ? undefined : { opacity: 0 }}
            transition={{ duration: 0.18, ease: 'easeOut' }}
          >
            <motion.section
              className="upload-dialog"
              role="dialog"
              aria-modal="true"
              aria-labelledby="upload-dialog-title"
              initial={reduceMotion ? false : { opacity: 0, y: 10, scale: 0.985 }}
              animate={{ opacity: 1, y: 0, scale: 1 }}
              exit={reduceMotion ? undefined : { opacity: 0, y: 6, scale: 0.99 }}
              transition={{ duration: 0.2, ease: 'easeOut' }}
            >
              <div className="upload-dialog-topline"><span><i />{uploadState.phase === 'transferring' ? 'UPLOADING TO BACKEND' : uploadState.phase === 'processing' ? 'BACKEND ANALYSIS' : uploadState.status === 'failed' ? 'ANALYSIS FAILED' : uploadState.status === 'processing' ? 'VIDEO UPLOADED' : 'JOB COMPLETE'}</span>{uploadState.phase === 'complete' && <IconButton label="Close upload summary" onClick={() => finishUploadFlow(false)}><X size={15} /></IconButton>}</div>
              <div className={`upload-emblem${uploadState.phase === 'transferring' ? ' is-transferring' : ''}${uploadState.phase === 'processing' ? ' is-processing' : ''}${uploadState.phase === 'complete' && uploadState.status === 'done' ? ' is-complete' : ''}${uploadState.status === 'failed' ? ' is-failed' : ''}`}>
                <svg viewBox="0 0 76 76" aria-hidden="true">
                  <circle className="upload-emblem-track" cx="38" cy="38" r="32" />
                  <motion.circle className="upload-emblem-progress" cx="38" cy="38" r="32" strokeDasharray="201.1" initial={false} animate={{ strokeDashoffset: 201.1 * (1 - uploadState.progress / 100) }} transition={{ duration: reduceMotion ? 0 : 0.28, ease: 'easeOut' }} />
                </svg>
                <span>{uploadState.phase === 'complete' && uploadState.status === 'done' ? <Check size={22} /> : uploadState.status === 'failed' ? <AlertTriangle size={20} /> : uploadState.phase === 'processing' ? <LoaderCircle size={20} /> : <CloudUpload size={20} />}</span>
              </div>
              <div className="upload-dialog-copy">
                <h2 id="upload-dialog-title">{uploadState.phase === 'transferring' ? 'Uploading your video' : uploadState.phase === 'processing' ? 'Analysis in progress' : uploadState.status === 'failed' ? 'Analysis failed' : uploadState.status === 'processing' ? 'Video uploaded' : 'Analysis complete'}</h2>
                <p>{uploadState.phase === 'transferring'
                  ? 'The backend is receiving the file. It will save the video and queue analysis after upload.'
                  : uploadState.phase === 'processing'
                    ? `${uploadState.stage || 'The backend is processing the video.'} · progress is reported by the analysis job.`
                    : uploadState.status === 'failed'
                      ? `The video is stored, but backend analysis failed. ${uploadState.error ?? ''}`
                      : uploadState.status === 'processing'
                        ? 'The video was stored. Status could not be refreshed; you can check the job again in Investigations.'
                        : `The backend finished the job${uploadState.verdict ? ` · ${uploadState.verdict.replaceAll('_', ' ')}` : ''}${uploadState.violationCount ? ` · ${uploadState.violationCount} event${uploadState.violationCount === 1 ? '' : 's'}` : ''}.`}</p>
              </div>
              <div className="upload-file-row"><span className="upload-file-icon"><FileVideo2 size={16} /></span><span className="upload-file-copy"><strong title={uploadState.fileName}>{uploadState.fileName}</strong><small>{formatFileSize(uploadState.size)} · {uploadState.stage || 'Video file'}</small></span><span className="upload-file-progress">{Math.round(uploadState.progress)}%</span></div>
              <div className="upload-progress-track" role="progressbar" aria-label={uploadState.phase === 'transferring' ? 'Video upload progress' : 'Backend analysis progress'} aria-valuemin={0} aria-valuemax={100} aria-valuenow={Math.round(uploadState.progress)}><motion.i initial={false} animate={{ width: `${uploadState.progress}%` }} transition={{ duration: reduceMotion ? 0 : 0.24, ease: 'easeOut' }} /></div>
              <div className="upload-step-list">
                {uploadSteps.map((step, index) => {
                  const done = index < uploadStepIndex || (uploadState.phase === 'complete' && uploadState.status === 'done' && index === 2)
                  const active = (uploadState.phase === 'transferring' || uploadState.phase === 'processing') && index === uploadStepIndex
                  const failed = uploadState.phase === 'complete' && uploadState.status === 'failed' && index === 2
                  const waitingForStatus = uploadState.phase === 'complete' && uploadState.status === 'processing' && index === 2
                  return <div className={`upload-step${done ? ' done' : ''}${active ? ' active' : ''}${failed ? ' failed' : ''}`} key={step}><span>{done ? <Check size={11} /> : active ? <LoaderCircle size={11} /> : failed ? <X size={11} /> : String(index + 1).padStart(2, '0')}</span><strong>{step}</strong><i>{done ? 'Complete' : active ? uploadState.stage || 'In progress' : failed ? 'Failed' : waitingForStatus ? 'Check in Investigations' : 'Waiting'}</i></div>
                })}
              </div>
              <div className={`upload-truth-note${uploadState.phase === 'processing' || uploadState.phase === 'complete' ? ' server-truth-note' : ''}`}><Info size={13} /><span>{uploadState.phase === 'transferring' ? 'Upload progress reflects bytes sent. Analysis progress will come from the backend job.' : uploadState.error ? uploadState.error : uploadState.phase === 'processing' ? 'The percentage and stage are returned by GET /ui/jobs/{job_id}.' : uploadState.status === 'failed' ? 'The uploaded video and its database record remain available in the backend.' : 'The backend job status and result are ready in Investigations.'}</span></div>
              {uploadState.phase === 'complete' && <div className="upload-dialog-actions"><button className="button-primary" type="button" onClick={() => finishUploadFlow(true)}>View Investigations <ArrowUpRight size={14} /></button><button className="button-secondary" type="button" onClick={() => finishUploadFlow(false)}>Return to video</button></div>}
            </motion.section>
          </motion.div>
        )}
      </AnimatePresence>

      <AnimatePresence>
        {toast && (
          <motion.div
            key={toast.id}
            className="toast"
            role="status"
            initial={reduceMotion ? false : { opacity: 0, y: 6 }}
            animate={{ opacity: 1, y: 0 }}
            exit={reduceMotion ? undefined : { opacity: 0, y: 4 }}
            transition={{ duration: 0.16, ease: 'easeOut' }}
          >
            <span className="toast-check"><Check size={13} /></span><span>{toast.message}</span>
            <IconButton label="Dismiss notification" onClick={() => setToast(null)}><X size={14} /></IconButton>
          </motion.div>
        )}
      </AnimatePresence>
    </div>
  )
}

export default App
