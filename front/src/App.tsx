import { useEffect, useRef, useState, type ChangeEvent, type DragEvent, type KeyboardEvent, type ReactNode } from 'react'
import { AnimatePresence, motion, useReducedMotion } from 'motion/react'
import {
  AlertTriangle,
  ArrowUpRight,
  Check,
  ChevronDown,
  CloudUpload,
  Clock3,
  FileVideo2,
  Film,
  FolderSearch,
  Info,
  LoaderCircle,
  RefreshCw,
  Search,
  ShieldCheck,
  Trash2,
  Upload,
  UserRound,
  Video,
  X,
  type LucideIcon,
} from 'lucide-react'
import { assignVideoWorker, getJobStatus, listWorkers, loadInvestigations, saveInvestigations, uploadVideo, type AnalysisStatus, type AnalysisViolation, type StoredInvestigation, type UiJobResponse, type Worker, type WorkerVideo } from './services/videoApi'
import { InvestigationPoster } from './components/InvestigationPoster'
import { InvestigationDetail } from './components/InvestigationDetail'
import { EmployeesView } from './components/EmployeesView'
import { getSavedReview, type ReviewDecision } from './hooks/useReviewStore'
import './App.css'

const MAX_FILE_SIZE = 200 * 1024 * 1024

type Section = 'video' | 'investigations' | 'employees'
type Toast = { id: number; message: string } | null
type SelectedVideo = { file: File | null; url: string; name: string; size: number; isObjectUrl: boolean; source: 'file' | 'server' }
type InvestigationItem = StoredInvestigation & { file: File | null; violations: AnalysisViolation[] }
type InvestigationFilter = 'all' | 'violations' | 'clean' | 'unassigned' | 'pending'
type UploadState = { fileName: string; size: number; progress: number; phase: 'transferring' | 'processing' | 'complete'; status: AnalysisStatus; stage: string; jobId?: string; error?: string; verdict?: string | null; violationCount?: number }

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

function currentTimestamp() {
  return new Date().toISOString()
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
    posterUrl: job.poster_url ?? item.posterUrl,
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
    posterUrl: item.posterUrl,
    verdict: item.verdict,
    violationCount: item.violationCount,
    error: item.error,
    workerId: item.workerId ?? null,
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
  workers,
}: {
  items: InvestigationItem[]
  loading: boolean
  error: string
  onRetry: () => void
  onOpen: (item: InvestigationItem) => void
  onRemove: (item: InvestigationItem) => void
  onNewVideo: () => void
  workers: Worker[]
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
  const unassignedTotal = items.filter((item) => !item.workerId).length
  const visibleItems = items
    .filter((item) => item.fileName.toLowerCase().includes(query.trim().toLowerCase()))
    .filter((item) => {
      if (filter === 'violations') return item.status === 'done' && hasViolation(item)
      if (filter === 'clean') return item.status === 'done' && !hasViolation(item)
      if (filter === 'unassigned') return !item.workerId
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
          <p>Review recordings, analysis results, and playback.</p>
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
              const employee = workers.find((entry) => entry.id === item.workerId)
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
                    posterSource={item.posterUrl ?? ''}
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
                  {item.status === 'failed' && <button className="failed-case-remove" type="button" title="Remove this recording from the list" aria-label={`Remove ${item.fileName} from the list`} onClick={(event) => { event.stopPropagation(); onRemove(item) }}><Trash2 size={13} /></button>}
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
  const [section, setSection] = useState<Section>('video')
  const [fileSelection, setFileSelection] = useState<SelectedVideo | null>(null)
  const [fileDuration, setFileDuration] = useState<number | null>(null)
  const [fileError, setFileError] = useState('')
  const [dragging, setDragging] = useState(false)
  const [toast, setToast] = useState<Toast>(null)
  const [investigations, setInvestigations] = useState<InvestigationItem[]>(() => loadInvestigations().map((item) => ({ ...item, file: null, violations: [] })))
  const investigationsRef = useRef(investigations)
  const [investigationsLoading, setInvestigationsLoading] = useState(false)
  const [investigationsError, setInvestigationsError] = useState('')
  const [investigationsRevision, setInvestigationsRevision] = useState(0)
  const [uploadState, setUploadState] = useState<UploadState | null>(null)
  const [selectedInvestigation, setSelectedInvestigation] = useState<InvestigationItem | null>(null)
  const [workers, setWorkers] = useState<Worker[]>([])
  const [workersLoading, setWorkersLoading] = useState(false)
  const [workersError, setWorkersError] = useState('')
  const [uploadWorkerId, setUploadWorkerId] = useState('')

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

  const previewFailed = fileError.startsWith('This video cannot be previewed')
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
    if (nextSection === 'employees' || (nextSection === 'investigations' && workers.length === 0)) void refreshWorkers()
    if (nextSection === 'investigations' && investigationsRef.current.length > 0) {
      setInvestigationsLoading(true)
      setInvestigationsError('')
      if (section === 'investigations') setInvestigationsRevision((current) => current + 1)
    }
    setSection(nextSection)
  }

  async function refreshWorkers() {
    setWorkersLoading(true)
    setWorkersError('')
    try {
      setWorkers(await listWorkers())
    } catch (error) {
      setWorkersError(error instanceof Error ? error.message : 'Could not load employees.')
    } finally {
      setWorkersLoading(false)
    }
  }

  function handleWorkerCreated(worker: Worker) {
    setWorkers((current) => [worker, ...current.filter((entry) => entry.id !== worker.id)])
    showToast(`${worker.name} added to employees`)
  }

  async function handleAssignWorker(videoId: string, workerId: string | null) {
    await assignVideoWorker(videoId, workerId)
    const next = investigationsRef.current.map((item) => item.videoId === videoId ? { ...item, workerId } : item)
    investigationsRef.current = next
    setInvestigations(next)
    persistInvestigations(next)
    setSelectedInvestigation((current) => current && current.videoId === videoId ? { ...current, workerId } : current)
    void refreshWorkers()
    showToast(workerId ? 'Worker linked to investigation' : 'Worker removed from investigation')
  }

  async function openWorkerVideo(video: WorkerVideo) {
    if (!video.jobId) return
    let item: InvestigationItem = {
      videoId: video.videoId,
      jobId: video.jobId,
      fileName: video.fileName,
      size: video.size,
      durationSeconds: video.durationSeconds,
      createdAt: video.createdAt,
      status: video.status === 'done' || video.status === 'failed' ? video.status : 'processing',
      stage: '',
      progress: 0,
      streamUrl: video.streamUrl,
      posterUrl: video.posterUrl ?? null,
      verdict: null,
      violationCount: 0,
      error: null,
      file: null,
      violations: [],
      workerId: video.workerId,
    }
    try {
      item = applyJobStatus(item, await getJobStatus(video.jobId))
    } catch {
      showToast('Showing the latest available investigation details')
    }
    setSelectedInvestigation(item)
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
      setFileError('Размер файла превышает ограничение 200 МБ.')
      return
    }
    setFileError('')
    setFileSelection({ file: candidate, url: URL.createObjectURL(candidate), name: candidate.name, size: candidate.size, isObjectUrl: true, source: 'file' })
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
      }, uploadWorkerId || undefined)
      let item: InvestigationItem = {
        videoId: accepted.video_id,
        jobId: accepted.job_id,
        fileName: currentFile.name,
        size: currentFile.size,
        durationSeconds: currentDuration,
        createdAt: currentTimestamp(),
        status: accepted.status,
        stage: 'В очереди',
        progress: 0,
        streamUrl: null,
        posterUrl: null,
        verdict: null,
        violationCount: 0,
        error: null,
        file: currentFile,
        violations: [],
        workerId: uploadWorkerId || null,
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
        showToast('Video stored · analysis failed')
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
    setUploadWorkerId('')
    if (openInvestigations) navigateToSection('investigations')
  }

  async function openInvestigation(item: InvestigationItem) {
    let current = item
    try {
      current = applyJobStatus(item, await getJobStatus(item.jobId))
      upsertInvestigation(current)
    } catch {
      showToast('Could not refresh analysis status · opening the recording')
    }
    setSelectedInvestigation(current)
  }

  function removeInvestigation(item: InvestigationItem) {
    const next = investigationsRef.current.filter((candidate) => candidate.jobId !== item.jobId)
    investigationsRef.current = next
    setInvestigations(next)
    persistInvestigations(next)
    showToast('Recording removed from this list')
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
              onClick={() => navigateToSection(id)}
              aria-current={section === id ? 'page' : undefined}
            >
              <Icon size={16} strokeWidth={1.8} aria-hidden="true" />
              <span>{label}</span>
            </button>
          ))}
        </nav>


      </aside>

      <div className="main-column">
        <header className="topbar">
          <div className="breadcrumb"><span>Compliance Intelligence</span><span className="breadcrumb-separator">/</span><strong>{pageTitle}</strong></div>
        </header>

        <main className="page-content" id="video-analysis">
          <AnimatePresence mode="wait" initial={false}>
            {section === 'employees' ? (
              <EmployeesView
                key="employees"
                workers={workers}
                loading={workersLoading}
                error={workersError}
                onRefresh={refreshWorkers}
                onCreated={handleWorkerCreated}
                onOpenVideo={openWorkerVideo}
              />
            ) : section === 'investigations' ? (
              <InvestigationGrid
                key="investigations"
                items={investigations}
                loading={investigationsLoading}
                error={investigationsError}
                onRetry={retryInvestigations}
                onOpen={openInvestigation}
                onRemove={removeInvestigation}
                onNewVideo={() => navigateToSection('video')}
                workers={workers}
              />
            ) : (
              <motion.div
                key={fileSelection ? 'file' : 'intake'}
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
                </div>

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
                          <div><span className="micro-label">{fileSelection.source === 'server' ? 'SAVED RECORDING' : 'VIDEO PREVIEW'}</span><h2>{fileSelection.source === 'server' ? 'Investigation video' : 'Selected video'}</h2></div>
                          <div className="file-actions">
                            {file && <button className="button-secondary compact-button" type="button" onClick={() => fileInputRef.current?.click()}><Upload size={14} /> Replace</button>}
                            <IconButton label="Remove selected video" onClick={removeFile}><X size={16} /></IconButton>
                          </div>
                        </div>
                        <div className="video-preview-wrap">
                          {fileUrl && !previewFailed && <video ref={videoRef} className="video-preview" src={fileUrl} controls playsInline onLoadedMetadata={(event) => setFileDuration(event.currentTarget.duration)} onError={() => setFileError('This video cannot be previewed in this browser.')} />}
                          {previewFailed && <div className="video-unavailable"><AlertTriangle size={18} /><span>{fileSelection.source === 'server' && !fileUrl ? 'Preview link unavailable' : 'Video preview unavailable'}</span></div>}
                          {!fileUrl && !previewFailed && <div className="video-unavailable"><AlertTriangle size={18} /><span>Loading preview…</span></div>}
                        </div>
                        <div className="selected-file-meta">
                          <div className="selected-file-name"><span className="file-type-icon"><FileVideo2 size={17} /></span><div><strong title={fileSelection.name}>{fileSelection.name}</strong><span>{formatFileSize(fileSelection.size)} <i /> {fileSelection.name.split('.').pop()?.toUpperCase() ?? 'VIDEO'}</span></div></div>
                          <div className="duration-meta"><Clock3 size={14} /><span>{fileDuration === null ? 'Duration unavailable' : formatTime(fileDuration)}</span></div>
                        </div>
                        {fileError && <p className="inline-file-error" role="alert"><AlertTriangle size={14} />{fileError}</p>}
                        <label className="upload-worker-assignment"><span>Associate with employee</span><select value={uploadWorkerId} onChange={(event) => setUploadWorkerId(event.target.value)} disabled={uploadState !== null}><option value="">No employee selected</option>{workers.map((worker) => <option value={worker.id} key={worker.id}>{worker.name}</option>)}</select></label>
                        {workers.length === 0 && <button className="worker-shortcut" type="button" onClick={() => navigateToSection('employees')}><UserRound size={12} /> Add a worker to link this recording <ArrowUpRight size={12} /></button>}
                        {file && <div className="upload-action-row"><button className="button-primary upload-video-button" type="button" onClick={startUpload} disabled={uploadState !== null}><CloudUpload size={15} /> Upload &amp; analyze</button><span>Video is saved after upload</span></div>}
                      </>
                    ) : (
                      <>
                        <div className="intake-panel-heading">
                          <div><span className="micro-label">NEW REVIEW</span><h2>Start a video review</h2><p>Choose a teller-operation recording to inspect.</p></div>
                          <span className="intake-step">01 <i>/ 03</i></span>
                        </div>
                        <div className={`drop-target${dragging ? ' is-dragging' : ''}${fileError ? ' has-error' : ''}`} onDragOver={handleDragOver} onDragLeave={handleDragLeave} onDrop={handleDrop}>
                          <div className="drop-target-content">
                            <div className="upload-glyph"><Upload size={19} strokeWidth={1.7} /></div>
                            <h3>{dragging ? 'Release to add recording' : 'Drop a recording here'}</h3>
                            <p>Drag a .mov, .mp4, or .m4v file here, or choose one from your device.</p>
                            <button className="button-primary" type="button" onClick={() => fileInputRef.current?.click()}><Upload size={15} /> Choose video</button>
                            <div className="upload-specs"><span>MOV · MP4 · M4V</span><i /><span>Up to 200 MB</span></div>
                          </div>
                          <div className="drop-corner drop-corner-tl" /><div className="drop-corner drop-corner-tr" /><div className="drop-corner drop-corner-bl" /><div className="drop-corner drop-corner-br" />
                        </div>
                        {fileError && <p className="upload-error" role="alert"><AlertTriangle size={14} />{fileError}</p>}
                        <label className="upload-worker-assignment"><span>Associate with employee</span><select value={uploadWorkerId} onChange={(event) => setUploadWorkerId(event.target.value)} disabled={uploadState !== null}><option value="">No employee selected</option>{workers.map((worker) => <option value={worker.id} key={worker.id}>{worker.name}</option>)}</select></label>
                        {workers.length === 0 && <button className="worker-shortcut" type="button" onClick={() => navigateToSection('employees')}><UserRound size={12} /> Add a worker to link this recording <ArrowUpRight size={12} /></button>}
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
                        <li><span className="workflow-number">02</span><div><strong>Upload and analyze</strong><p>Your recording is saved and analysis progress appears here.</p></div></li>
                        <li><span className="workflow-number">03</span><div><strong>Review the result</strong><p>Open your recording and findings from Investigations.</p></div></li>
                      </ol>
                    </section>
                    <section className="requirements-section">
                      <div className="requirements-heading"><h3>Recording requirements</h3><Info size={14} aria-hidden="true" /></div>
                      <dl><div><dt>Format</dt><dd>.mov · .mp4 · .m4v</dd></div><div><dt>Maximum size</dt><dd>200 MB</dd></div><div><dt>Analysis</dt><dd>Automatic</dd></div></dl>
                    </section>
                  </aside>
                </motion.section>
              </motion.div>
            )}
          </AnimatePresence>
        </main>
      </div>

      {selectedInvestigation && <InvestigationDetail key={selectedInvestigation.jobId} item={selectedInvestigation} workers={workers} onAssignWorker={handleAssignWorker} onClose={() => setSelectedInvestigation(null)} />}

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
              <div className="upload-dialog-topline"><span><i />{uploadState.phase === 'transferring' ? 'UPLOADING VIDEO' : uploadState.phase === 'processing' ? 'VIDEO ANALYSIS' : uploadState.status === 'failed' ? 'ANALYSIS FAILED' : uploadState.status === 'processing' ? 'VIDEO UPLOADED' : 'JOB COMPLETE'}</span>{uploadState.phase === 'complete' && <IconButton label="Close upload summary" onClick={() => finishUploadFlow(false)}><X size={15} /></IconButton>}</div>
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
                  ? 'Your video is uploading. Analysis will begin when the upload is complete.'
                  : uploadState.phase === 'processing'
                    ? `${uploadState.stage || 'Analysis is in progress.'}`
                    : uploadState.status === 'failed'
                      ? `The video is stored, but analysis failed. ${uploadState.error ?? ''}`
                      : uploadState.status === 'processing'
                        ? 'The video was stored. Status could not be refreshed; you can check the job again in Investigations.'
                        : `Analysis finished${uploadState.verdict ? ` · ${uploadState.verdict.replaceAll('_', ' ')}` : ''}${uploadState.violationCount ? ` · ${uploadState.violationCount} event${uploadState.violationCount === 1 ? '' : 's'}` : ''}.`}</p>
              </div>
              <div className="upload-file-row"><span className="upload-file-icon"><FileVideo2 size={16} /></span><span className="upload-file-copy"><strong title={uploadState.fileName}>{uploadState.fileName}</strong><small>{formatFileSize(uploadState.size)} · {uploadState.stage || 'Video file'}</small></span><span className="upload-file-progress">{Math.round(uploadState.progress)}%</span></div>
              <div className="upload-progress-track" role="progressbar" aria-label={uploadState.phase === 'transferring' ? 'Video upload progress' : 'Automatic analysis progress'} aria-valuemin={0} aria-valuemax={100} aria-valuenow={Math.round(uploadState.progress)}><motion.i initial={false} animate={{ width: `${uploadState.progress}%` }} transition={{ duration: reduceMotion ? 0 : 0.24, ease: 'easeOut' }} /></div>
              <div className="upload-step-list">
                {uploadSteps.map((step, index) => {
                  const done = index < uploadStepIndex || (uploadState.phase === 'complete' && uploadState.status === 'done' && index === 2)
                  const active = (uploadState.phase === 'transferring' || uploadState.phase === 'processing') && index === uploadStepIndex
                  const failed = uploadState.phase === 'complete' && uploadState.status === 'failed' && index === 2
                  const waitingForStatus = uploadState.phase === 'complete' && uploadState.status === 'processing' && index === 2
                  return <div className={`upload-step${done ? ' done' : ''}${active ? ' active' : ''}${failed ? ' failed' : ''}`} key={step}><span>{done ? <Check size={11} /> : active ? <LoaderCircle size={11} /> : failed ? <X size={11} /> : String(index + 1).padStart(2, '0')}</span><strong>{step}</strong><i>{done ? 'Complete' : active ? uploadState.stage || 'In progress' : failed ? 'Failed' : waitingForStatus ? 'Check in Investigations' : 'Waiting'}</i></div>
                })}
              </div>
              <div className={`upload-truth-note${uploadState.phase === 'processing' || uploadState.phase === 'complete' ? ' server-truth-note' : ''}`}><Info size={13} /><span>{uploadState.phase === 'transferring' ? 'Upload progress reflects the video being sent. Analysis progress updates automatically.' : uploadState.error ? uploadState.error : uploadState.phase === 'processing' ? 'Analysis progress and stage update automatically.' : uploadState.status === 'failed' ? 'Your uploaded video remains available in Investigations.' : 'The analysis result is ready in Investigations.'}</span></div>
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
