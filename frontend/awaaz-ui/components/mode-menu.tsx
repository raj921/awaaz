"use client"

import { useEffect, useId, useRef, useState } from "react"
import {
  CheckIcon,
  ChevronDownIcon,
  MessageSquareIcon,
  MicIcon,
} from "lucide-react"
import { MODES, MODE_GROUPS, modeInfo, type Mode } from "@/lib/modes"

/**
 * Mode dropdown. Closes on Escape and outside click, and (unlike the version
 * this replaces) is reachable by keyboard: the trigger and items are real
 * buttons with the ARIA wiring a menu needs, and focus returns to the trigger
 * when the menu closes.
 */
export function ModeMenu({
  mode,
  setMode,
  disabled = false,
}: {
  mode: Mode
  setMode: (m: Mode) => void
  disabled?: boolean
}) {
  const [open, setOpen] = useState(false)
  const ref = useRef<HTMLDivElement>(null)
  const triggerRef = useRef<HTMLButtonElement>(null)
  const menuId = useId()

  useEffect(() => {
    if (!open) return
    const onDoc = (e: MouseEvent) => {
      if (!ref.current?.contains(e.target as Node)) setOpen(false)
    }
    const onKey = (e: KeyboardEvent) => {
      if (e.key === "Escape") {
        setOpen(false)
        triggerRef.current?.focus()
      }
    }
    document.addEventListener("mousedown", onDoc)
    document.addEventListener("keydown", onKey)
    return () => {
      document.removeEventListener("mousedown", onDoc)
      document.removeEventListener("keydown", onKey)
    }
  }, [open])

  const info = modeInfo(mode)

  return (
    <div ref={ref} className="relative">
      <button
        ref={triggerRef}
        type="button"
        onClick={() => setOpen((o) => !o)}
        disabled={disabled}
        aria-haspopup="menu"
        aria-expanded={open}
        aria-controls={open ? menuId : undefined}
        className="flex items-center gap-2 rounded-full border border-white/10 bg-white/[0.028] py-1.5 pr-3 pl-4 text-[13px] text-white/80 transition-colors hover:border-white/25 disabled:cursor-not-allowed disabled:opacity-50"
      >
        {info.voice ? (
          <MicIcon className="size-3.5 text-white/50" />
        ) : (
          <MessageSquareIcon className="size-3.5 text-white/50" />
        )}
        <span>
          {info.group} <span className="text-white/50">· {info.label}</span>
        </span>
        <ChevronDownIcon
          className={`size-3.5 text-white/40 transition-transform ${open ? "rotate-180" : ""}`}
        />
      </button>

      {open && (
        <div
          id={menuId}
          role="menu"
          aria-label="Select mode"
          className="absolute right-0 z-20 mt-2 min-w-60 rounded-2xl border border-white/10 bg-[#141414] p-1.5 shadow-2xl shadow-black/60"
        >
          {MODE_GROUPS.map((g) => (
            <div key={g} className="p-1">
              <p className="px-2 pt-1 pb-1.5 text-[10px] font-medium tracking-[0.2em] text-white/30 uppercase">
                {g}
              </p>
              {MODES.filter((m) => m.group === g).map((m) => (
                <button
                  key={m.id}
                  type="button"
                  role="menuitemradio"
                  aria-checked={mode === m.id}
                  onClick={() => {
                    setMode(m.id)
                    setOpen(false)
                    triggerRef.current?.focus()
                  }}
                  className={`flex w-full items-center gap-2.5 rounded-xl px-2.5 py-2 text-sm transition-colors ${
                    mode === m.id
                      ? "bg-white/[0.06] text-white"
                      : "text-white/70 hover:bg-white/[0.04] hover:text-white"
                  }`}
                >
                  {m.voice ? (
                    <MicIcon className="size-4 text-white/50" />
                  ) : (
                    <MessageSquareIcon className="size-4 text-white/50" />
                  )}
                  {m.label}
                  {m.provider === "sarvam" && (
                    <span className="text-[10px] text-white/30">API</span>
                  )}
                  {mode === m.id && (
                    <CheckIcon className="ml-auto size-3.5 text-white/70" />
                  )}
                </button>
              ))}
            </div>
          ))}
        </div>
      )}
    </div>
  )
}
