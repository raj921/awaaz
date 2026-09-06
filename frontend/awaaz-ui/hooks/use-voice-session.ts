"use client"

import { useCallback, useEffect, useRef, useState } from "react"
import { AUDIO, API_URL } from "@/lib/config"

export type VoiceState = "idle" | "recording" | "thinking" | "speaking"

export type VoiceSessionOptions = {
  provider: string
  llm?: string
  /** Called after each completed turn (reply received). */
  onTurn?: () => void
}

export type VoiceSession = {
  state: VoiceState
  volume: number
  heard: string | null
  reply: string | null
  error: string | null
  start: () => Promise<void>
  stop: () => void
  holdStart: () => void
  holdEnd: () => void
}

// MediaRecorder gives compressed audio; both upstreams want 16 kHz mono WAV.
async function toWav16k(blob: Blob): Promise<string> {
  const ctx = new AudioContext()
  try {
    const buf = await ctx.decodeAudioData(await blob.arrayBuffer())
    const src = buf.getChannelData(0)
    const out = new Int16Array(
      Math.floor((src.length * AUDIO.sampleRate) / buf.sampleRate),
    )
    for (let i = 0; i < out.length; i++) {
      const s = src[Math.floor((i * buf.sampleRate) / AUDIO.sampleRate)]
      out[i] = Math.max(-32768, Math.min(32767, Math.round(s * 32768)))
    }
    const wav = new ArrayBuffer(44 + out.length * 2)
    const v = new DataView(wav)
    const wstr = (o: number, s: string) => {
      for (let i = 0; i < s.length; i++) v.setUint8(o + i, s.charCodeAt(i))
    }
    wstr(0, "RIFF")
    v.setUint32(4, 36 + out.length * 2, true)
    wstr(8, "WAVEfmt ")
    v.setUint32(16, 16, true)
    v.setUint16(20, 1, true)
    v.setUint16(22, 1, true)
    v.setUint32(24, AUDIO.sampleRate, true)
    v.setUint32(28, AUDIO.sampleRate * 2, true)
    v.setUint16(32, 2, true)
    v.setUint16(34, 16, true)
    wstr(36, "data")
    v.setUint32(40, out.length * 2, true)
    new Int16Array(wav, 44).set(out)
    const bytes = new Uint8Array(wav)
    let bin = ""
    for (let i = 0; i < bytes.length; i += 8192) {
      bin += String.fromCharCode(...bytes.subarray(i, i + 8192))
    }
    return btoa(bin)
  } finally {
    void ctx.close()
  }
}

/**
 * useVoiceSession owns one recording turn: mic → MediaRecorder → WAV →
 * POST /api/v1/voice → play the reply. Plain HTTP, no socket — the room
 * architecture is gone by user decision.
 *
 * Push-to-talk: the button is hold-to-talk only. There is no VAD: the turn
 * ends exactly when the button releases (pointer up, or the 30 s cap). A
 * mid-thought pause can never cut the sentence, which was the room's
 * unsolvable failure mode.
 */
export function useVoiceSession({
  provider,
  llm,
  onTurn,
}: VoiceSessionOptions): VoiceSession {
  const [state, setState] = useState<VoiceState>("idle")
  const [volume, setVolume] = useState(0)
  const [heard, setHeard] = useState<string | null>(null)
  const [reply, setReply] = useState<string | null>(null)
  const [error, setError] = useState<string | null>(null)

  const streamRef = useRef<MediaStream | null>(null)
  const recRef = useRef<MediaRecorder | null>(null)
  const ctxRef = useRef<AudioContext | null>(null)
  const rafRef = useRef<number | null>(null)
  const timeoutRef = useRef<number | null>(null)
  const audioRef = useRef<HTMLAudioElement | null>(null)
  const onTurnRef = useRef(onTurn)
  const stateRef = useRef<VoiceState>("idle")
  useEffect(() => {
    stateRef.current = state
  }, [state])

  const stopMeter = useCallback(() => {
    if (rafRef.current !== null) {
      cancelAnimationFrame(rafRef.current)
      rafRef.current = null
    }
    setVolume(0)
  }, [])

  const stopMic = useCallback(() => {
    streamRef.current?.getTracks().forEach((t) => t.stop())
    streamRef.current = null
    void ctxRef.current?.close().catch(() => {})
    ctxRef.current = null
    stopMeter()
  }, [stopMeter])

  const stopRecording = useCallback(() => {
    if (timeoutRef.current !== null) {
      clearTimeout(timeoutRef.current)
      timeoutRef.current = null
    }
    recRef.current?.stop()
  }, [])

  const sendVoice = useCallback(
    async (blob: Blob) => {
      if (blob.size === 0) {
        setState("idle")
        return
      }
      setState("thinking")
      try {
        const wavB64 = await toWav16k(blob)
        const res = await fetch(`${API_URL}/api/v1/voice`, {
          method: "POST",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify({
            lang: "auto",
            wav_b64: wavB64,
            provider,
            ...(llm && { llm }),
          }),
        })
        const data = await res.json()
        if (!res.ok)
          throw new Error(data?.error?.message ?? `Request failed (${res.status})`)
        setHeard(data.heard)
        setReply(data.reply)
        setState("speaking")
        onTurnRef.current?.()
        const url = URL.createObjectURL(
          new Blob([Uint8Array.from(atob(data.audio_b64), (c) => c.charCodeAt(0))], {
            type: "audio/wav",
          }),
        )
        const audio = new Audio(url)
        audioRef.current = audio
        const finish = () => {
          URL.revokeObjectURL(url)
          audioRef.current = null
          setState("idle")
        }
        audio.onended = finish
        audio.onerror = finish
        await audio.play().catch(() => {
          setError("could not play reply")
          finish()
        })
      } catch (e) {
        setError(e instanceof Error ? e.message : "voice request failed")
        setState("idle")
      } finally {
        stopMic()
      }
    },
    [provider, llm, stopMic],
  )

  /** Hold to talk: opens the mic and records until holdEnd (button release). */
  const start = useCallback(async () => {
    if (stateRef.current !== "idle") return
    setError(null)
    setHeard(null)
    setReply(null)
    try {
      const stream = await navigator.mediaDevices.getUserMedia({ audio: true })
      streamRef.current = stream
      const ctx = new AudioContext()
      ctxRef.current = ctx
      const analyser = ctx.createAnalyser()
      analyser.fftSize = 256
      ctx.createMediaStreamSource(stream).connect(analyser)
      const data = new Uint8Array(analyser.frequencyBinCount)
      const tick = () => {
        if (!ctxRef.current) return
        analyser.getByteTimeDomainData(data)
        let peak = 0
        for (const x of data) peak = Math.max(peak, Math.abs(x - 128) / 128)
        setVolume(Math.min(1, peak * 2))
        rafRef.current = requestAnimationFrame(tick)
      }
      tick()

      const rec = new MediaRecorder(stream)
      // Guard the browser's stop-flush: some builds deliver a final
      // dataavailable only on the next tick, so a fast release could
      // otherwise record an empty clip and surface "Unable to decode".
      const chunks: Blob[] = []
      rec.ondataavailable = (e) => {
        if (e.data.size > 0) chunks.push(e.data)
      }
      rec.onstop = () => {
        recRef.current = null
        const blob = new Blob(chunks)
        if (blob.size === 0) {
          setState("idle")
          setError("no speech captured — hold a little longer")
          stopMic()
          return
        }
        void sendVoice(blob)
      }
      recRef.current = rec
      rec.start()
      setState("recording")
      // Cap stays: whisper likes clips under 30 s and the gateway caps
      // bodies at 4 MiB (~2 min of 16 kHz WAV) — this never gets close.
      timeoutRef.current = window.setTimeout(() => {
        stopRecording()
      }, 30000)
    } catch {
      setError("microphone unavailable")
      setState("idle")
      stopMic()
    }
  }, [sendVoice, stopMic, stopRecording])

  /** Release to send: ends the recording; the request fires from onstop. */
  const stop = useCallback(() => {
    stopRecording()
  }, [stopRecording])

  /** Full teardown (leaving the voice stage): stop everything, discard. */
  const abort = useCallback(() => {
    stopRecording()
    stopMic()
    audioRef.current?.pause()
    setState("idle")
  }, [stopRecording, stopMic])

  return {
    state,
    volume,
    heard,
    reply,
    error,
    start,
    stop: abort,
    holdStart: () => {
      void start()
    },
    holdEnd: stop,
  }
}
