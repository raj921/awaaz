"use client"

import { useEffect, useMemo, useRef, type ReactNode } from "react"
import {
  AssistantRuntimeProvider,
  useLocalRuntime,
  type ChatModelAdapter,
} from "@assistant-ui/react"
import { API_URL } from "@/lib/config"
import type { Fact, RecalledFact } from "@/hooks/use-memory"
import type { Provider } from "@/lib/modes"

export type { Provider } from "@/lib/modes"

/** Matches the gateway's error envelope. */
type ApiError = { error?: { code?: string; message?: string } }

type ChatResponse = ApiError & {
  reply?: string
  memory_used?: RecalledFact[]
  memory_saved?: Fact[]
}

export function AwaazRuntimeProvider({
  provider,
  onMemory,
  children,
}: Readonly<{
  provider: Provider
  /** Reports per-turn memory activity so the UI can surface it. */
  onMemory?: (used: RecalledFact[], saved: Fact[]) => void
  children: ReactNode
}>) {
  // Read at run time so switching provider never resets the thread.
  const providerRef = useRef(provider)
  useEffect(() => {
    providerRef.current = provider
  }, [provider])

  // Held in a ref for the same reason as provider: the adapter is memoized
  // once, so closing over the prop directly would pin the first render's
  // callback forever.
  const onMemoryRef = useRef(onMemory)
  useEffect(() => {
    onMemoryRef.current = onMemory
  }, [onMemory])

  const runtime = useLocalRuntime(
    useMemo<ChatModelAdapter>(
      () => ({
        async run({ messages, abortSignal }) {
          const res = await fetch(`${API_URL}/api/v1/chat`, {
            method: "POST",
            headers: { "Content-Type": "application/json" },
            body: JSON.stringify({
              messages: messages
                .map((m) => ({
                  role: m.role,
                  content: m.content
                    .filter((c) => c.type === "text")
                    .map((c) => c.text)
                    .join("\n"),
                }))
                // The gateway rejects any message with empty content with a
                // 422, so an attachment-only or tool-only turn used to fail
                // the whole request. Drop them instead.
                .filter((m) => m.content.trim() !== ""),
              max_tokens: 200,
              provider: providerRef.current,
            }),
            signal: abortSignal,
          })

          // A non-JSON body (a proxy's HTML 502 page, say) used to throw a
          // raw SyntaxError at the user. Parse defensively and report the
          // status instead.
          let data: ChatResponse | null = null
          try {
            data = (await res.json()) as ChatResponse
          } catch {
            data = null
          }
          if (!res.ok) {
            throw new Error(
              data?.error?.message ?? `Request failed (${res.status})`
            )
          }
          if (typeof data?.reply !== "string") {
            throw new Error("The model returned an empty reply.")
          }
          onMemoryRef.current?.(data.memory_used ?? [], data.memory_saved ?? [])
          return { content: [{ type: "text", text: data.reply }] }
        },
      }),
      []
    )
  )

  return (
    <AssistantRuntimeProvider runtime={runtime}>
      {children}
    </AssistantRuntimeProvider>
  )
}
