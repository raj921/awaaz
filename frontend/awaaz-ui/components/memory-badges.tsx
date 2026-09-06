"use client"

import { BrainIcon, SparklesIcon } from "lucide-react"
import type { Fact, RecalledFact } from "@/hooks/use-memory"

/**
 * Per-turn memory indicators.
 *
 * Memory used to be invisible: facts were injected into the prompt and the
 * user simply had to trust that it happened. These badges make each turn
 * self-explaining — what the assistant *recalled* to answer, and what it
 * *learned* from what you just said.
 */

export function RecalledBadges({
  used,
  className = "",
}: {
  used: RecalledFact[]
  className?: string
}) {
  if (used.length === 0) return null
  return (
    <div
      className={`flex flex-wrap items-center justify-center gap-1.5 ${className}`}
      aria-label="Facts recalled for this answer"
    >
      <span className="flex items-center gap-1 text-[10px] tracking-[0.18em] text-white/35 uppercase">
        <BrainIcon className="size-3" />
        Remembered
      </span>
      {used.map((f) => (
        <span
          key={f.id}
          title={`importance ${f.importance} · retrievability ${f.retrievability}`}
          className="rounded-full border border-sky-400/25 bg-sky-400/10 px-2.5 py-0.5 text-xs text-sky-200/90"
        >
          {f.text}
        </span>
      ))}
    </div>
  )
}

export function SavedBadges({
  saved,
  className = "",
}: {
  saved: Fact[]
  className?: string
}) {
  if (saved.length === 0) return null
  return (
    <div
      className={`flex flex-wrap items-center justify-center gap-1.5 ${className}`}
      aria-label="Facts learned from this turn"
    >
      <span className="flex items-center gap-1 text-[10px] tracking-[0.18em] text-white/35 uppercase">
        <SparklesIcon className="size-3" />
        Learned
      </span>
      {saved.map((f) => (
        <span
          key={f.id}
          className="voice-rise rounded-full border border-emerald-400/25 bg-emerald-400/10 px-2.5 py-0.5 text-xs text-emerald-200/90"
        >
          {f.text}
        </span>
      ))}
    </div>
  )
}
