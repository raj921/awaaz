"use client"

import { MicIcon } from "lucide-react"
import {
  VoiceOrb,
  type VoiceOrbState,
} from "@/components/assistant-ui/elements/voice"
import type { VoiceSession, VoiceState } from "@/hooks/use-voice-session"
import { RecalledBadges, SavedBadges } from "@/components/memory-badges"

const STATUS_LABEL: Record<VoiceState, string> = {
  idle: "Tap to start",
  connecting: "Connecting",
  listening: "Listening",
  thinking: "Thinking",
  speaking: "Speaking",
}

/**
 * The session state and the orb's visual state are deliberately separate
 * vocabularies. The old page conflated them — it mapped "thinking" onto the
 * orb's "connecting" and then used that same value to label the UI, so the
 * status text read "Thinking" while the socket was still connecting and
 * there was no way to tell a slow handshake from a slow model.
 */
function orbState(state: VoiceState): VoiceOrbState {
  switch (state) {
    case "connecting":
    case "thinking":
      return "connecting"
    case "listening":
      return "listening"
    case "speaking":
      return "speaking"
    default:
      return "idle"
  }
}

export function VoiceStage({ session }: { session: VoiceSession }) {
  const {
    state,
    volume,
    room,
    heard,
    reply,
    error,
    holding,
    memoryUsed,
    memorySaved,
  } = session
  const orb = orbState(state)
  const live = state === "listening" || state === "speaking"
  const busy = live || state === "connecting" || state === "thinking"

  return (
    <section className="flex min-h-[calc(100svh-11rem)] w-full flex-col items-center justify-center text-center md:min-h-0">
      <div className="flex items-center gap-2" aria-live="polite">
        <span
          className={`size-2 rounded-full ${
            live
              ? "ab-live-dot"
              : busy
                ? "animate-pulse bg-amber-400"
                : "bg-white/30"
          }`}
        />
        <span
          className={`text-xs font-medium tracking-[0.25em] uppercase ${
            busy ? "voice-busy" : "text-white/50"
          }`}
        >
          {STATUS_LABEL[state]}
        </span>
      </div>

      <div className="relative my-2 flex items-center justify-center py-4">
        <div
          className="ab-orb-glow absolute size-72 rounded-full"
          aria-hidden
        />
        <VoiceOrb
          state={orb}
          volume={volume}
          className="relative size-48 md:size-60"
        />
      </div>

      {/* Fixed-height slot: invitation and transcript swap without shifting
          the session button. */}
      <div className="flex min-h-32 w-full flex-col items-center justify-center gap-1.5 px-2 pb-6">
        {(heard || reply) && (
          <>
            {heard && (
              <p
                key={`h-${heard}`}
                className="voice-rise text-base text-white/45"
              >
                “{heard}”
              </p>
            )}
            {reply && (
              <p
                key={`r-${reply}`}
                className="voice-rise text-xl leading-snug font-medium text-balance text-[#fafafa] md:text-2xl"
              >
                {reply}
              </p>
            )}
            {/* Why the assistant answered the way it did, and what it took
                away from the turn — memory made observable. */}
            <RecalledBadges used={memoryUsed} className="pt-1.5" />
            <SavedBadges saved={memorySaved} className="pt-0.5" />
          </>
        )}
        {!heard && !reply && state === "idle" && (
          <>
            <p className="text-2xl font-medium tracking-tight text-[#fafafa] md:text-3xl">
              हलो बोलिए
            </p>
            <p className="ab-grad-text pt-0.5 text-2xl font-medium tracking-tight md:text-3xl">
              హలో చెప్పండి
            </p>
            <p className="pt-1.5 text-xs text-white/40">
              Open a room, hold to talk — release to send. Pauses never cut you
              off.
            </p>
          </>
        )}
        {error && (
          <p role="alert" className="text-sm text-red-400">
            {error}
          </p>
        )}
      </div>

      <div className="relative">
        <div
          className="ab-pill-glow absolute inset-x-4 -bottom-2 h-4 rounded-full"
          aria-hidden
        />
        {!room ? (
          <button
            type="button"
            onClick={() => void session.start()}
            disabled={state === "connecting"}
            className="relative flex h-12 items-center gap-2 rounded-full bg-white px-8 text-sm font-medium text-[#0c0c0c] transition-[filter,transform] hover:brightness-95 active:scale-95 disabled:cursor-not-allowed disabled:opacity-60"
          >
            <MicIcon className="size-4" />
            {state === "connecting" ? "Connecting…" : "Talk"}
          </button>
        ) : (
          <div className="flex items-center gap-3">
            <button
              type="button"
              // Pointer events cover mouse, touch and pen in one path.
              // Capture keeps the release on this element even if the finger
              // slides off, so a drag can no longer strand the room in a
              // permanently-held state.
              onPointerDown={(e) => {
                e.currentTarget.setPointerCapture(e.pointerId)
                session.holdStart()
              }}
              onPointerUp={session.holdEnd}
              onPointerCancel={session.holdEnd}
              onLostPointerCapture={session.holdEnd}
              // Keyboard parity: space/enter hold while pressed.
              onKeyDown={(e) => {
                if ((e.key === " " || e.key === "Enter") && !e.repeat) {
                  e.preventDefault()
                  session.holdStart()
                }
              }}
              onKeyUp={(e) => {
                if (e.key === " " || e.key === "Enter") {
                  e.preventDefault()
                  session.holdEnd()
                }
              }}
              aria-pressed={holding}
              className={`relative flex h-12 touch-none items-center gap-2 rounded-full px-8 text-sm font-medium transition-[filter,transform] select-none active:scale-95 ${
                holding
                  ? "ab-grad text-[#0c0c0c]"
                  : "bg-white text-[#0c0c0c] hover:brightness-95"
              }`}
            >
              <MicIcon className="size-4" />
              {holding ? "Release to send" : "Hold to talk"}
            </button>
            <button
              type="button"
              onClick={session.stop}
              className="text-sm text-white/45 transition-colors hover:text-white"
            >
              End
            </button>
          </div>
        )}
      </div>
    </section>
  )
}
