/** Provider/stage selection shared by the page and the runtime provider. */

export type Provider = "awaaz" | "sarvam"

export type Mode =
  "ab-voice" | "ab-voice-sxl" | "ab-chat" | "sarvam-voice" | "sarvam-chat"

export type ModeInfo = {
  id: Mode
  label: string
  group: string
  provider: Provider
  voice: boolean
  llm?: "sarvam"
}

export const MODES: readonly ModeInfo[] = [
  {
    id: "ab-voice-sxl",
    label: "Voice · Sarvam LLM",
    group: "Awaaz",
    provider: "awaaz",
    voice: true,
    llm: "sarvam",
  },
  {
    id: "ab-voice",
    label: "Voice · Qwen LLM",
    group: "Awaaz",
    provider: "awaaz",
    voice: true,
  },
  {
    id: "ab-chat",
    label: "Chat",
    group: "Awaaz",
    provider: "awaaz",
    voice: false,
  },
  {
    id: "sarvam-voice",
    label: "Voice",
    group: "Sarvam",
    provider: "sarvam",
    voice: true,
  },
  {
    id: "sarvam-chat",
    label: "Chat",
    group: "Sarvam",
    provider: "sarvam",
    voice: false,
  },
] as const

export const DEFAULT_MODE: Mode = "ab-voice-sxl"

/**
 * Look up a mode. The previous version ended in a non-null assertion, so an
 * unknown id (a stale value restored from storage, say) crashed the whole
 * page on render instead of degrading to the default.
 */
export function modeInfo(mode: Mode): ModeInfo {
  return (
    MODES.find((m) => m.id === mode) ??
    MODES.find((m) => m.id === DEFAULT_MODE) ??
    MODES[0]!
  )
}

export const MODE_GROUPS: readonly string[] = [
  ...new Set(MODES.map((m) => m.group)),
]
