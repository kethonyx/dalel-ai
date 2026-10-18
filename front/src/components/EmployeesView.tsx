import { useEffect, useState, type FormEvent } from 'react'
import { AnimatePresence, motion, useReducedMotion } from 'motion/react'
import { ArrowLeft, ArrowUpRight, CalendarDays, Check, FileVideo2, LoaderCircle, Plus, Search, ShieldCheck, UserRound, Users, Video, X } from 'lucide-react'
import { createWorker, listWorkerVideos, type Worker, type WorkerVideo } from '../services/videoApi'

function initials(name: string) {
  return name.trim().split(/\s+/).slice(0, 2).map((part) => part[0]?.toUpperCase() ?? '').join('')
}

function dateLabel(value: string) {
  const date = new Date(value)
  return Number.isNaN(date.getTime()) ? 'Date unavailable' : new Intl.DateTimeFormat('en-GB', { dateStyle: 'medium' }).format(date)
}

function sizeLabel(bytes: number) {
  return bytes >= 1024 ** 2 ? `${(bytes / 1024 ** 2).toFixed(1)} MB` : `${Math.round(bytes / 1024)} KB`
}

function performanceIndex(durationSeconds: number, violations: number) {
  if (durationSeconds <= 0) return null
  return Math.max(0, Math.min(100, Math.round(100 - violations * 60 / durationSeconds)))
}

function durationLabel(seconds: number) {
  const minutes = Math.round(seconds / 60)
  return minutes >= 60 ? `${(minutes / 60).toFixed(1)} h` : `${minutes} min`
}

type Props = {
  workers: Worker[]
  loading: boolean
  error: string
  onRefresh: () => void
  onCreated: (worker: Worker) => void
  onOpenVideo: (video: WorkerVideo) => void
}

export function EmployeesView({ workers, loading, error, onRefresh, onCreated, onOpenVideo }: Props) {
  const reduceMotion = useReducedMotion()
  const [query, setQuery] = useState('')
  const [creating, setCreating] = useState(false)
  const [name, setName] = useState('')
  const [createError, setCreateError] = useState('')
  const [saving, setSaving] = useState(false)
  const [selectedWorker, setSelectedWorker] = useState<Worker | null>(null)
  const [workerVideos, setWorkerVideos] = useState<WorkerVideo[]>([])
  const [videosLoading, setVideosLoading] = useState(false)
  const [videosError, setVideosError] = useState('')

  useEffect(() => {
    if (!selectedWorker) return
    let cancelled = false
    listWorkerVideos(selectedWorker.id).then((items) => {
      if (!cancelled) setWorkerVideos(items)
    }).catch((reason: unknown) => {
      if (!cancelled) setVideosError(reason instanceof Error ? reason.message : 'Could not load recordings.')
    }).finally(() => {
      if (!cancelled) setVideosLoading(false)
    })
    return () => { cancelled = true }
  }, [selectedWorker])

  const visibleWorkers = workers.filter((worker) => worker.name.toLocaleLowerCase().includes(query.trim().toLocaleLowerCase()))
  const totalVideos = workers.reduce((sum, worker) => sum + worker.videoCount, 0)
  const teamDuration = workers.reduce((sum, worker) => sum + worker.analyzedDurationSeconds, 0)
  const teamViolations = workers.reduce((sum, worker) => sum + worker.violationCount, 0)
  const teamIndex = performanceIndex(teamDuration, teamViolations)

  async function saveWorker(event: FormEvent<HTMLFormElement>) {
    event.preventDefault()
    const cleanName = name.trim()
    if (!cleanName) return
    setSaving(true)
    setCreateError('')
    try {
      const worker = await createWorker(cleanName)
      onCreated(worker)
      setName('')
      setCreating(false)
    } catch (reason) {
      setCreateError(reason instanceof Error ? reason.message : 'Could not add this worker.')
    } finally {
      setSaving(false)
    }
  }

  return (
    <motion.section
      className="employees-view"
      initial={reduceMotion ? false : { opacity: 0, y: 6 }}
      animate={{ opacity: 1, y: 0 }}
      exit={reduceMotion ? undefined : { opacity: 0, y: -4 }}
      transition={{ duration: 0.2, ease: 'easeOut' }}
      aria-labelledby="employees-title"
    >
      <div className="page-heading employees-heading">
        <div><span className="micro-label">TEAM DIRECTORY</span><h1 id="employees-title">Employees</h1><p>Manage workers and review their associated recordings.</p></div>
        <button className="button-primary" type="button" onClick={() => { setCreating(true); setCreateError('') }}><Plus size={15} /> Add worker</button>
      </div>

      <div className="employees-overview">
        <div className="employees-overview-icon"><Users size={17} /></div>
        <div><span>Registered workers</span><strong>{workers.length.toString().padStart(2, '0')}</strong></div>
        <i />
        <div className="employees-overview-icon video"><Video size={16} /></div>
        <div><span>Linked recordings</span><strong>{totalVideos.toString().padStart(2, '0')}</strong></div>
        <i />
        <div><span>Team index</span><strong>{teamIndex === null ? '—' : `${teamIndex}/100`}</strong></div>
        <div className="employees-overview-spacer" />
        <button className="icon-button employees-refresh" type="button" onClick={onRefresh} aria-label="Refresh employees" title="Refresh"><LoaderCircle size={15} className={loading ? 'is-spinning' : ''} /></button>
      </div>

      <div className="employees-toolbar">
        <label className="investigation-search"><Search size={15} /><input value={query} onChange={(event) => setQuery(event.target.value)} placeholder="Search employees" aria-label="Search employees" /></label>
        <span className="employees-result-count">{visibleWorkers.length} {visibleWorkers.length === 1 ? 'worker' : 'workers'}</span>
      </div>

      {error ? (
        <div className="employees-state" role="alert"><div className="placeholder-icon"><Users size={19} /></div><h2>Could not load employees</h2><p>{error}</p><button className="button-secondary" type="button" onClick={onRefresh}>Try again</button></div>
      ) : loading && workers.length === 0 ? (
        <div className="employee-grid" aria-busy="true" aria-label="Loading employees">{[0, 1, 2].map((item) => <div className="employee-skeleton" key={item}><i /><span /><b /></div>)}</div>
      ) : visibleWorkers.length === 0 ? (
        <div className="employees-state">
          <div className="employees-empty-mark"><span /><UserRound size={22} /></div>
          <span className="micro-label">YOUR TEAM</span>
          <h2>{workers.length === 0 ? 'Start your employee directory' : 'No matching employees'}</h2>
          <p>{workers.length === 0 ? 'Add a worker to connect recordings with the people in your team.' : 'Try another name or clear your search.'}</p>
          {workers.length === 0 ? <button className="button-primary" type="button" onClick={() => setCreating(true)}><Plus size={14} /> Add first worker</button> : <button className="button-secondary" type="button" onClick={() => setQuery('')}>Clear search</button>}
        </div>
      ) : (
        <div className="employee-grid">
          {visibleWorkers.map((worker, index) => (
            <motion.button
              className="employee-card"
              type="button"
              key={worker.id}
              onClick={() => { setWorkerVideos([]); setVideosError(''); setVideosLoading(true); setSelectedWorker(worker) }}
              initial={reduceMotion ? false : { opacity: 0, y: 8 }}
              animate={{ opacity: 1, y: 0 }}
              transition={{ duration: 0.22, delay: reduceMotion ? 0 : Math.min(index * 0.035, 0.2) }}
              whileHover={reduceMotion ? undefined : { y: -3 }}
            >
              <span className="employee-card-top"><span className="employee-avatar">{initials(worker.name)}</span><span className="employee-card-open"><ArrowUpRight size={15} /></span></span>
              <span className="employee-card-name">{worker.name}</span>
              <span className="employee-card-meta"><CalendarDays size={12} /> Added {dateLabel(worker.createdAt)}</span>
              <span className="employee-score"><ShieldCheck size={12} /> Index <strong>{performanceIndex(worker.analyzedDurationSeconds, worker.violationCount) === null ? '—' : `${performanceIndex(worker.analyzedDurationSeconds, worker.violationCount)}/100`}</strong></span>
              <span className="employee-card-divider" />
              <span className="employee-card-footer"><span><Video size={13} /> Recordings</span><strong>{worker.videoCount.toString().padStart(2, '0')}</strong></span>
            </motion.button>
          ))}
        </div>
      )}

      <section className="employee-index-preview" aria-label="Performance index">
        <div className="index-preview-mark"><ShieldCheck size={16} /></div>
        <div className="index-preview-copy"><span className="micro-label">TEAM PERFORMANCE</span><h2>{teamIndex === null ? 'Index is being calculated' : `Team index · ${teamIndex}/100`}</h2><p>{teamDuration > 0 ? `${durationLabel(teamDuration)} analyzed · ${teamViolations} detected violations` : 'Complete an assigned video analysis to calculate the index.'} · Each violation reduces the score by 1 point per minute analyzed.</p></div>
        <div className="index-preview-score">{teamIndex === null ? '—' : teamIndex}<small>/100</small></div>
      </section>

      <AnimatePresence>
        {creating && (
          <motion.div className="worker-modal-backdrop" initial={{ opacity: 0 }} animate={{ opacity: 1 }} exit={{ opacity: 0 }} onMouseDown={(event) => { if (event.target === event.currentTarget && !saving) setCreating(false) }}>
            <motion.section className="worker-modal" role="dialog" aria-modal="true" aria-labelledby="new-worker-title" initial={reduceMotion ? false : { opacity: 0, y: 12, scale: 0.98 }} animate={{ opacity: 1, y: 0, scale: 1 }} exit={reduceMotion ? undefined : { opacity: 0, y: 8, scale: 0.985 }} transition={{ duration: 0.2 }}>
              <div className="worker-modal-head"><span className="worker-modal-icon"><UserRound size={17} /></span><button className="icon-button" type="button" aria-label="Close" onClick={() => setCreating(false)} disabled={saving}><X size={16} /></button></div>
              <span className="micro-label">TEAM DIRECTORY</span>
              <h2 id="new-worker-title">Add a worker</h2>
              <p>Worker details are saved to your directory.</p>
              <form onSubmit={saveWorker}>
                <label className="worker-name-field"><span>Full name</span><input autoFocus maxLength={200} value={name} onChange={(event) => setName(event.target.value)} placeholder="Enter worker name" required /></label>
                {createError && <p className="worker-form-error" role="alert">{createError}</p>}
                <div className="worker-modal-actions"><button className="button-secondary" type="button" onClick={() => setCreating(false)} disabled={saving}>Cancel</button><button className="button-primary" type="submit" disabled={saving || !name.trim()}>{saving ? <LoaderCircle size={14} className="is-spinning" /> : <Check size={14} />} {saving ? 'Saving…' : 'Save worker'}</button></div>
              </form>
            </motion.section>
          </motion.div>
        )}
      </AnimatePresence>

      <AnimatePresence>
        {selectedWorker && (
          <motion.div className="worker-profile-backdrop" initial={{ opacity: 0 }} animate={{ opacity: 1 }} exit={{ opacity: 0 }} onMouseDown={(event) => { if (event.target === event.currentTarget) setSelectedWorker(null) }}>
            <motion.section className="worker-profile" role="dialog" aria-modal="true" aria-labelledby="worker-profile-title" initial={reduceMotion ? false : { opacity: 0, x: 22 }} animate={{ opacity: 1, x: 0 }} exit={reduceMotion ? undefined : { opacity: 0, x: 18 }} transition={{ duration: 0.22, ease: 'easeOut' }}>
              <header className="worker-profile-head"><button className="button-secondary worker-back" type="button" onClick={() => setSelectedWorker(null)}><ArrowLeft size={14} /> Employees</button><button className="icon-button" type="button" aria-label="Close employee profile" onClick={() => setSelectedWorker(null)}><X size={17} /></button></header>
              <div className="worker-profile-scroll">
                <div className="worker-profile-hero"><span className="employee-avatar large">{initials(selectedWorker.name)}</span><div><span className="micro-label">WORKER PROFILE</span><h2 id="worker-profile-title">{selectedWorker.name}</h2><p><CalendarDays size={13} /> Added {dateLabel(selectedWorker.createdAt)}</p></div></div>
                <div className="worker-profile-stats"><div><span>Linked recordings</span><strong>{workerVideos.length.toString().padStart(2, '0')}</strong></div><div><span>Profile status</span><strong className="worker-active-status"><i /> Active</strong></div></div>
                <section className="worker-recordings"><div className="worker-section-heading"><div><span className="micro-label">VIDEO LIBRARY</span><h3>Investigations</h3></div><span>{workerVideos.length.toString().padStart(2, '0')}</span></div>
                  {videosLoading ? <div className="worker-detail-loading"><LoaderCircle size={17} className="is-spinning" /> Loading recordings…</div> : videosError ? <div className="worker-detail-error" role="alert">{videosError}<button className="button-secondary" type="button" onClick={() => { setVideosLoading(true); setVideosError(''); setSelectedWorker({ ...selectedWorker }) }}>Retry</button></div> : workerVideos.length === 0 ? <div className="worker-recordings-empty"><FileVideo2 size={19} /><strong>No recordings linked</strong><span>Assign a recording to this worker from an investigation.</span></div> : (
                    <div className="worker-video-list">{workerVideos.map((video) => <button className="worker-video-row" key={video.videoId} type="button" onClick={() => { setSelectedWorker(null); onOpenVideo(video) }}><span className="worker-video-icon"><FileVideo2 size={15} /></span><span className="worker-video-copy"><strong>{video.fileName}</strong><small>{sizeLabel(video.size)} · {dateLabel(video.createdAt)}</small></span><span className={`worker-video-status ${video.status ?? 'processing'}`}><i />{video.status === 'done' ? 'Complete' : video.status === 'failed' ? 'Failed' : 'Processing'}</span><ArrowUpRight className="worker-video-arrow" size={14} /></button>)}</div>
                  )}
                </section>
                <section className="worker-index-card"><span className="worker-index-icon"><ShieldCheck size={17} /></span><div><span className="micro-label">PERFORMANCE INDEX</span><h3>{performanceIndex(selectedWorker.analyzedDurationSeconds, selectedWorker.violationCount) === null ? 'Not enough data yet' : `${performanceIndex(selectedWorker.analyzedDurationSeconds, selectedWorker.violationCount)} / 100`}</h3><p>{selectedWorker.analyzedVideoCount} analyzed recordings · {durationLabel(selectedWorker.analyzedDurationSeconds)} analyzed · {selectedWorker.violationCount} detected violations. Each violation reduces the score by 1 point per minute analyzed.</p></div><div className="worker-index-lines" aria-hidden="true"><i /><i /><i /></div></section>
              </div>
            </motion.section>
          </motion.div>
        )}
      </AnimatePresence>
    </motion.section>
  )
}
