"use client"

import { useEffect, useRef, useState } from "react"
import { Button } from "@/components/ui/button"
import { Thread } from "@/components/assistant-ui/elements/thread.aui"
import { ModeMenu } from "@/components/mode-menu"
import { VoiceStage } from "@/components/voice-stage"
import { useMemory } from "@/hooks/use-memory"
import { useVoiceSession } from "@/hooks/use-voice-session"
import { API_URL } from "@/lib/config"
import { DEFAULT_MODE, modeInfo, type Mode } from "@/lib/modes"
import { AwaazRuntimeProvider } from "./awaaz-runtime"

export default function Page() {
  const [mode, setMode] = useState<Mode>(DEFAULT_MODE)
  const [factInput, setFactInput] = useState("")

  const { provider, voice, llm } = modeInfo(mode)
  const memory = useMemory()
  const session = useVoiceSession({ provider, llm, onTurn: memory.refreshSoon })

  const warmedRef = useRef(false)
  useEffect(() => {
    if (!voice || warmedRef.current) return
    warmedRef.current = true
    // Preload the cold GPU containers once, when voice first becomes the
    // active stage.
    void fetch(`${API_URL}/api/v1/warm`, { method: "POST" }).catch(() => {})
  }, [voice])

  // Leaving the voice stage must stop the mic; otherwise the microphone
  // stayed open in the background while the user was in chat.
  const active = session.state !== "idle"
  const stopSession = session.stop
  useEffect(() => {
    if (!voice && active) stopSession()
  }, [voice, active, stopSession])

  async function saveFact() {
    const text = factInput.trim()
    if (!text) return
    // Only clear the input once the write actually succeeded — the old code
    // cleared it optimistically and lost the text whenever the POST failed.
    if (await memory.remember(text)) setFactInput("")
  }

  return (
    <div className="dark flex min-h-svh flex-col bg-[#0c0c0c] font-sans text-white md:h-svh md:overflow-hidden">
      <header className="ab-hairline flex h-12 shrink-0 items-center justify-between border-b px-5">
        <a
          href="#"
          aria-label="Awaaz home"
          className="text-sm font-medium tracking-tight"
        >
          A<span className="ab-grad-text">waaz</span>
        </a>
        <ModeMenu mode={mode} setMode={setMode} />
      </header>

      <main className="mx-auto flex min-h-0 w-full max-w-6xl flex-1 flex-col px-6 py-3">
        {voice ? (
          <VoiceStage session={session} />
        ) : (
          <AwaazRuntimeProvider provider={provider} onTurn={memory.refreshSoon}>
            <section className="h-[70svh] min-h-0 w-full md:h-full md:flex-1">
              <div className="ab-hairline h-full overflow-hidden rounded-3xl border bg-white/[0.02]">
                <Thread />
              </div>
            </section>
          </AwaazRuntimeProvider>
        )}
      </main>

      <footer className="ab-hairline shrink-0 border-t">
        <div className="mx-auto flex w-full max-w-6xl flex-col items-center gap-2 px-6 py-3 sm:flex-row">
          <div className="flex w-full gap-2 sm:w-auto sm:min-w-64">
            <label htmlFor="remember-input" className="sr-only">
              Remember a fact
            </label>
            <input
              id="remember-input"
              value={factInput}
              onChange={(e) => setFactInput(e.target.value)}
              onKeyDown={(e) => {
                if (e.key === "Enter") void saveFact()
              }}
              placeholder="Remember this..."
              className="ab-hairline min-w-0 flex-1 rounded-full border bg-white/[0.02] px-4 py-1.5 text-sm text-[#efefef] outline-none placeholder:text-white/30 focus:border-white/30"
            />
            <Button
              size="sm"
              onClick={() => void saveFact()}
              disabled={memory.pending || factInput.trim() === ""}
              className="h-8 rounded-full bg-white text-[#0c0c0c] hover:bg-white/90"
            >
              Save
            </Button>
          </div>
          <ul className="flex max-h-16 w-full flex-1 flex-wrap gap-1.5 overflow-y-auto sm:justify-end">
            {memory.facts.map((f) => (
              <li
                key={f.id}
                className="voice-rise ab-hairline flex items-center gap-1.5 rounded-full border bg-white/[0.03] py-1 pr-1.5 pl-3 text-xs text-[#efefef]"
              >
                <span className="min-w-0">{f.text}</span>
                <button
                  type="button"
                  onClick={() => void memory.forget(f.text)}
                  aria-label={`Forget ${f.text}`}
                  className="shrink-0 rounded-full px-1 text-white/40 transition-colors hover:bg-red-500/15 hover:text-red-400"
                >
                  ×
                </button>
              </li>
            ))}
          </ul>
        </div>
      </footer>
    </div>
  )
}
