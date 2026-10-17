import { useState } from 'react'

export type ReviewDecision = 'pending' | 'confirmed' | 'dismissed'
export type CaseReview = {
  comment: string
  eventDecisions: Record<string, ReviewDecision>
  savedAt: string | null
}

const emptyReview: CaseReview = { comment: '', eventDecisions: {}, savedAt: null }
const reviewKey = (jobId: string) => `forte-investigation-review:${jobId}`

export function getSavedReview(jobId: string): CaseReview {
  try {
    const value: unknown = JSON.parse(localStorage.getItem(reviewKey(jobId)) ?? 'null')
    if (!value || typeof value !== 'object') return emptyReview
    const review = value as Record<string, unknown>
    const decisions: Record<string, ReviewDecision> = {}
    if (review.eventDecisions && typeof review.eventDecisions === 'object') {
      for (const [key, decision] of Object.entries(review.eventDecisions as Record<string, unknown>)) {
        if (decision === 'pending' || decision === 'confirmed' || decision === 'dismissed') decisions[key] = decision
      }
    }
    return {
      comment: typeof review.comment === 'string' ? review.comment : '',
      eventDecisions: decisions,
      savedAt: typeof review.savedAt === 'string' ? review.savedAt : null,
    }
  } catch {
    return emptyReview
  }
}

export function useReviewStore(jobId: string) {
  const [review, setReview] = useState<CaseReview>(() => getSavedReview(jobId))
  function updateReview(patch: Partial<Omit<CaseReview, 'savedAt'>>) {
    setReview((current) => ({ ...current, ...patch, savedAt: null }))
  }
  function setEventDecision(eventIndex: number, decision: ReviewDecision) {
    setReview((current) => ({
      ...current,
      eventDecisions: { ...current.eventDecisions, [String(eventIndex)]: decision },
      savedAt: null,
    }))
  }
  function saveReview() {
    const saved = { ...review, savedAt: new Date().toISOString() }
    try {
      localStorage.setItem(reviewKey(jobId), JSON.stringify(saved))
      setReview(saved)
      return true
    } catch {
      return false
    }
  }
  return { review, updateReview, setEventDecision, saveReview }
}
