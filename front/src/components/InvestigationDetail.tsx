import { useRef, useState } from 'react'
import { AnimatePresence, motion, useReducedMotion } from 'motion/react'
import { AlertTriangle, Check, CheckCircle2, Clock3, MessageSquareText, ShieldCheck, UserRound, X } from 'lucide-react'
import type { AnalysisViolation, StoredInvestigation } from '../services/videoApi'
import { employees } from '../employees'
import { useReviewStore, type ReviewDecision } from '../hooks/useReviewStore'

type InvestigationDetailItem = StoredInvestigation & {
  file: File | null
  violations: AnalysisViolation[]
}

function formatTime(seconds: number) {
  const value = Math.max(0, Math.floor(seconds))
  return `${String(Math.floor(value / 60)).padStart(2, '0')}:${String(value % 60).padStart(2, '0')}`
}

function formatDate(value: string) {
  const date = new Date(value)
  return Number.isNaN(date.getTime()) ? 'Date unavailable' : new Intl.DateTimeFormat('en-GB', { dateStyle: 'medium' }).format(date)
}

function evidenceSource(value: string) {
  return value.startsWith('data:') ? value : `data:image/jpeg;base64,${value}`
}

function statusLabel(decision: ReviewDecision) {
  return decision === 'confirmed' ? 'Confirmed' : decision === 'dismissed' ? 'Dismissed' : 'Pending review'
}

export function InvestigationDetail({ item, onClose }: { item: InvestigationDetailItem; onClose: () => void }) {
  const reduceMotion = useReducedMotion()
  const videoRef = useRef<HTMLVideoElement>(null)
  const [activeEvent, setActiveEvent] = useState<number | null>(null)
  const { review, updateReview, setEventDecision, saveReview } = useReviewStore(item.jobId)
  const events = item.violations ?? []

  function jumpTo(seconds: number, index: number) {
    setActiveEvent(index)
    if (!videoRef.current) return
    videoRef.current.currentTime = seconds
    void videoRef.current.play().catch(() => undefined)
  }

  function handleSave() {
    const saved = saveReview()
    if (!saved) return
    window.dispatchEvent(new CustomEvent('forte-review-saved', { detail: { jobId: item.jobId } }))
  }

  return (
    <AnimatePresence>
      <motion.div
        className="investigation-detail-backdrop"
        initial={reduceMotion ? false : { opacity: 0 }}
        animate={{ opacity: 1 }}
        exit={reduceMotion ? undefined : { opacity: 0 }}
        onMouseDown={(event) => { if (event.target === event.currentTarget) onClose() }}
      >
        <motion.section
          className="investigation-detail"
          role="dialog"
          aria-modal="true"
          aria-labelledby="case-detail-title"
          initial={reduceMotion ? false : { opacity: 0, x: 22 }}
          animate={{ opacity: 1, x: 0 }}
          exit={reduceMotion ? undefined : { opacity: 0, x: 18 }}
          transition={{ duration: 0.2, ease: 'easeOut' }}
        >
          <header className="detail-topbar">
            <div><span className="micro-label">INVESTIGATION CASE</span><h2 id="case-detail-title">Case {item.fileName.replace(/\.[^.]+$/, '') || 'Video'}</h2></div>
            <button className="icon-button" type="button" aria-label="Close case details" onClick={onClose}><X size={17} /></button>
          </header>

          <div className="detail-layout">
            <main className="detail-main-column">
              <section className="detail-player-panel" aria-label="Investigation video">
                {item.streamUrl ? <video ref={videoRef} src={item.streamUrl} controls playsInline preload="metadata" /> : (
                  <div className="detail-video-empty"><AlertTriangle size={19} /><span>Video preview is not available right now.</span></div>
                )}
                <div className="detail-video-meta"><span><Clock3 size={13} /> {item.durationSeconds === null ? 'Duration unavailable' : formatTime(item.durationSeconds)}</span><span>{item.fileName} · {formatDate(item.createdAt)}</span></div>
                <div className="case-timeline" aria-label="Video event timeline">
                  <div className="case-timeline-track" />
                  {events.map((event, index) => {
                    const ratio = item.durationSeconds && item.durationSeconds > 0 ? Math.min(1, event.timecode_sec / item.durationSeconds) : 0
                    return <button key={`${event.timecode_sec}-${index}`} className={`case-timeline-mark${activeEvent === index ? ' active' : ''}`} style={{ left: `${ratio * 100}%` }} type="button" aria-label={`Jump to ${formatTime(event.timecode_sec)}: ${event.type}`} onClick={() => jumpTo(event.timecode_sec, index)} />
                  })}
                </div>
                <div className="case-timeline-labels"><span>00:00</span><span>{events.length} {events.length === 1 ? 'event' : 'events'}</span><span>{item.durationSeconds === null ? '--:--' : formatTime(item.durationSeconds)}</span></div>
              </section>

              <section className="case-review-panel" aria-labelledby="review-title">
                <div className="case-section-title"><div><span className="micro-label">HUMAN REVIEW</span><h3 id="review-title">Review decision</h3></div><span className={`review-save-status${review.savedAt ? ' saved' : ''}`}>{review.savedAt ? 'Saved locally' : 'Unsaved changes'}</span></div>
                <label className="review-field"><span><UserRound size={13} /> Assign employee</span><select value={review.employeeId} onChange={(event) => updateReview({ employeeId: event.target.value })}><option value="">Unassigned</option>{employees.map((employee) => <option value={employee.id} key={employee.id}>{employee.name}</option>)}</select></label>
                <label className="review-field"><span><MessageSquareText size={13} /> Reviewer comment</span><textarea value={review.comment} onChange={(event) => updateReview({ comment: event.target.value })} placeholder="Add context for this review" rows={3} /></label>
                <button className="button-primary save-review-button" type="button" onClick={handleSave}><CheckCircle2 size={14} /> Save review</button>
              </section>
            </main>

            <aside className="detail-events-panel" aria-labelledby="case-events-title">
              <div className="case-section-title"><div><span className="micro-label">ANALYSIS RESULTS</span><h3 id="case-events-title">Events <span>{events.length.toString().padStart(2, '0')}</span></h3></div><span className={`verdict-pill ${item.verdict === 'violation' || (!item.verdict && events.length) ? 'violation' : 'clean'}`}><i />{item.verdict === 'violation' || (!item.verdict && events.length) ? 'Violation detected' : 'No violation'}</span></div>
              {events.length === 0 ? <div className="detail-no-events"><ShieldCheck size={20} /><strong>No events reported</strong><span>The completed analysis returned no violations.</span></div> : (
                <div className="detail-events-list">
                  {events.map((event, index) => {
                    const decision = review.eventDecisions[String(index)] ?? 'pending'
                    return (
                      <article className={`detail-event${activeEvent === index ? ' active' : ''}`} key={`${event.timecode_sec}-${index}`}>
                        <button className="detail-event-main" type="button" onClick={() => jumpTo(event.timecode_sec, index)}>
                          <span className="detail-event-heading"><strong>{event.type}</strong><span>{formatTime(event.timecode_sec)}</span></span>
                          <span className="detail-event-description">{event.description}</span>
                        </button>
                        {event.evidence_frames?.[0] && <img className="event-evidence-frame" src={evidenceSource(event.evidence_frames[0].image_base64)} alt={`Evidence at ${formatTime(event.evidence_frames[0].timestamp_sec)}`} />}
                        {event.rule && <div className="event-rule-ref">{event.rule.document}{event.rule.section ? ` · ${event.rule.section}` : ''}{event.rule.url && <a href={event.rule.url} target="_blank" rel="noreferrer">Source</a>}</div>}
                        <div className="detail-event-review"><span className={`review-decision-label ${decision}`}>{statusLabel(decision)}</span><div><button type="button" className={`decision-button confirm${decision === 'confirmed' ? ' selected' : ''}`} onClick={() => setEventDecision(index, 'confirmed')}><Check size={12} /> Confirm</button><button type="button" className={`decision-button dismiss${decision === 'dismissed' ? ' selected' : ''}`} onClick={() => setEventDecision(index, 'dismissed')}><X size={12} /> Dismiss</button></div></div>
                      </article>
                    )
                  })}
                </div>
              )}
            </aside>
          </div>
        </motion.section>
      </motion.div>
    </AnimatePresence>
  )
}
