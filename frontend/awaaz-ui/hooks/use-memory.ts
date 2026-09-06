"use client"

import { useCallback, useEffect, useRef, useState } from "react"
import { API_URL } from "@/lib/config"

export type Fact = { id: number; text: string }

/** A fact the assistant drew on to answer, with its scoring. */
export type RecalledFact = Fact & {
  importance: number
  retrievability: number
}

/**
 * useMemory talks to the gateway's memory endpoints.
 *
 * Fixes over the inline version this replaces: every write is awaited and
 * error-checked (a failed POST used to be followed by an unconditional
 * refresh that made it look like it had worked), in-flight requests are
 * aborted on unmount, and a failed refresh no longer silently blanks the
 * panel.
 */
export function useMemory() {
  const [facts, setFacts] = useState<Fact[]>([])
  const [error, setError] = useState<string | null>(null)
  const [pending, setPending] = useState(false)
  const abortRef = useRef<AbortController | null>(null)
  const mountedRef = useRef(true)

  useEffect(() => {
    mountedRef.current = true
    return () => {
      mountedRef.current = false
      abortRef.current?.abort()
    }
  }, [])

  const refresh = useCallback(async () => {
    abortRef.current?.abort()
    const controller = new AbortController()
    abortRef.current = controller
    try {
      const res = await fetch(`${API_URL}/api/v1/memory`, {
        signal: controller.signal,
      })
      if (!res.ok) throw new Error(`HTTP ${res.status}`)
      const data = (await res.json()) as { facts?: Fact[] }
      if (!mountedRef.current) return
      setFacts(data.facts ?? [])
      setError(null)
    } catch (err) {
      if ((err as Error).name === "AbortError" || !mountedRef.current) return
      // Keep whatever is on screen; the sidecar being down must not wipe
      // the panel or block chat.
      setError("memory sidecar unavailable")
    }
  }, [])

  // Initial load. This is a genuine external-system subscription (fetching
  // from the sidecar), not derived state; the lint rule cannot distinguish
  // the two because `refresh` calls setState once the request resolves.
  useEffect(() => {
    // eslint-disable-next-line react-hooks/set-state-in-effect
    void refresh()
  }, [refresh])

  const mutate = useCallback(
    async (path: string, text: string) => {
      const trimmed = text.trim()
      if (!trimmed || pending) return false
      setPending(true)
      try {
        const res = await fetch(`${API_URL}${path}`, {
          method: "POST",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify({ text: trimmed }),
        })
        if (!res.ok) throw new Error(`HTTP ${res.status}`)
        await refresh()
        setError(null)
        return true
      } catch {
        if (mountedRef.current) setError("could not reach the memory sidecar")
        return false
      } finally {
        if (mountedRef.current) setPending(false)
      }
    },
    [pending, refresh]
  )

  const remember = useCallback(
    (text: string) => mutate("/api/v1/memory", text),
    [mutate]
  )
  const forget = useCallback(
    (text: string) => mutate("/api/v1/memory/forget", text),
    [mutate]
  )

  return { facts, error, pending, remember, forget, refresh }
}
