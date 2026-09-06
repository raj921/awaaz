"use client"

import { useCallback, useEffect, useRef, useState } from "react"
import { AUDIO, API_URL, wsURL } from "@/lib/config"

export type VoiceState =
  "idle" | "connecting" | "listening" | "thinking" | "speaking"

export type VoiceSessionOptions = {
  provider: string
  llm?: string
}

export type VoiceSession = {
  state: VoiceState
  volume: number
  room: string | null
  heard: string | null
  reply: string | null
  error: string | null
  holding: boolean
  start: () => Promise<void>
  stop: () => void
  holdStart: () => void
  holdEnd: () => void
}

/** Server → client messages on the voice socket. */
type ServerMessage =
  | { type: "room"; id: string }
  | { type: "state"; value: "listening" | "thinking" | "speaking" | "ended" }
  | { type: "reply"; heard?: string; reply?: string }
  | { type: "error"; message: string }

/**
 * useVoiceSession owns the entire voice room lifecycle: socket, microphone,
 * capture graph and reply playback.
 *
 * This used to live inline in the page component, where several bugs hid:
 *
 *  - The mic was opened AFTER `ws.onopen` had already fired, and the capture
 *    node was wired up asynchronously. Between "connected" and "mic ready"
 *    the room was live but silent — the socket connected and nothing ever
 *    listened.
 *  - `holdStart` only set `holding` when the socket happened to be OPEN, so
 *    pressing the button during the connect handshake did nothing at all and
 *    the matching `holdEnd` then bailed out early on `if (!holding) return`.
 *    The button looked dead.
 *  - The resampler read `inp[Math.floor(i * ctx.sampleRate / 16000)]` with no
 *    bounds check and no anti-aliasing, emitting `undefined` → NaN → 0
 *    samples at the tail of every block.
 *  - Playback used a bare `new Audio()` with no gate, so overlapping replies
 *    stacked on top of each other.
 */
export function useVoiceSession({
  provider,
  llm,
}: VoiceSessionOptions): VoiceSession {
  const [state, setState] = useState<VoiceState>("idle")
  const [volume, setVolume] = useState(0)
  const [room, setRoom] = useState<string | null>(null)
  const [heard, setHeard] = useState<string | null>(null)
  const [reply, setReply] = useState<string | null>(null)
  const [error, setError] = useState<string | null>(null)
  const [holding, setHolding] = useState(false)

  const wsRef = useRef<WebSocket | null>(null)
  const streamRef = useRef<MediaStream | null>(null)
  const ctxRef = useRef<AudioContext | null>(null)
  const processorRef = useRef<ScriptProcessorNode | null>(null)
  const rafRef = useRef<number | null>(null)
  const audioRef = useRef<HTMLAudioElement | null>(null)
  const objectURLRef = useRef<string | null>(null)
  // Buffer hold intent so a press during the handshake is not lost: the
  // flag is read when the socket opens rather than dropped on the floor.
  const holdRef = useRef(false)
  // Guards against a stale async start() resolving after stop().
  const sessionRef = useRef(0)

  /** Send a JSON control frame if the socket is open. */
  const sendControl = useCallback((msg: Record<string, unknown>) => {
    const ws = wsRef.current
    if (ws?.readyState === WebSocket.OPEN) {
      ws.send(JSON.stringify(msg))
      return true
    }
    return false
  }, [])

  /** Tear down the microphone graph. Safe to call repeatedly. */
  const stopMic = useCallback(() => {
    if (rafRef.current !== null) {
      cancelAnimationFrame(rafRef.current)
      rafRef.current = null
    }
    // Disconnect the processor before closing the context, otherwise its
    // onaudioprocess can fire once more against a closing context.
    const proc = processorRef.current
    if (proc) {
      proc.onaudioprocess = null
      proc.disconnect()
      processorRef.current = null
    }
    streamRef.current?.getTracks().forEach((t) => t.stop())
    streamRef.current = null
    const ctx = ctxRef.current
    ctxRef.current = null
    if (ctx && ctx.state !== "closed") void ctx.close().catch(() => {})
    setVolume(0)
  }, [])

  /** Stop any reply currently playing and release its blob URL. */
  const stopPlayback = useCallback(() => {
    const audio = audioRef.current
    if (audio) {
      audio.onended = null
      audio.onerror = null
      audio.pause()
      audioRef.current = null
    }
    if (objectURLRef.current) {
      URL.revokeObjectURL(objectURLRef.current)
      objectURLRef.current = null
    }
  }, [])

  const stop = useCallback(() => {
    sessionRef.current += 1
    holdRef.current = false
    const ws = wsRef.current
    if (ws && ws.readyState === WebSocket.OPEN) {
      // Ask for a clean server-side close so the room is logged as ended
      // rather than as a dropped connection.
      ws.send(JSON.stringify({ type: "stop" }))
    }
    ws?.close(1000, "client ended session")
    wsRef.current = null
    stopPlayback()
    stopMic()
    setRoom(null)
    setHolding(false)
    setState("idle")
  }, [stopMic, stopPlayback])

  /** Play one reply clip, telling the server when playback finishes so the
   *  server-side echo guard is released early. */
  const playReply = useCallback(
    (data: ArrayBuffer) => {
      stopPlayback() // never stack replies on top of each other
      const url = URL.createObjectURL(new Blob([data], { type: "audio/wav" }))
      objectURLRef.current = url
      const audio = new Audio(url)
      audioRef.current = audio

      const done = () => {
        if (objectURLRef.current === url) {
          URL.revokeObjectURL(url)
          objectURLRef.current = null
        }
        if (audioRef.current === audio) audioRef.current = null
        sendControl({ type: "played" })
      }
      audio.onended = done
      audio.onerror = () => {
        setError("could not play the reply audio")
        done()
      }
      void audio.play().catch(() => {
        // Autoplay policies block playback until the user has interacted;
        // the turn still succeeded, so surface it without killing the room.
        setError("tap once to allow audio playback")
        done()
      })
    },
    [sendControl, stopPlayback]
  )

  /**
   * Open the microphone and build the capture graph. Resolves only once
   * audio is actually flowing, so the caller can guarantee the room is
   * listening before it reports "connected".
   */
  const startMic = useCallback(async () => {
    const stream = await navigator.mediaDevices.getUserMedia({
      audio: {
        channelCount: 1,
        echoCancellation: true,
        noiseSuppression: true,
        autoGainControl: true,
      },
    })
    streamRef.current = stream

    // Ask for the target rate directly: when the device supports it the
    // browser resamples natively and our own resampling becomes a no-op.
    const ctx = new AudioContext({ sampleRate: AUDIO.sampleRate })
    ctxRef.current = ctx
    // Contexts start suspended under autoplay policies; without this the
    // processor never fires and the room hears pure silence.
    if (ctx.state === "suspended") await ctx.resume()

    const src = ctx.createMediaStreamSource(stream)

    const analyser = ctx.createAnalyser()
    analyser.fftSize = 256
    src.connect(analyser)
    const samples = new Uint8Array(analyser.frequencyBinCount)
    const tick = () => {
      if (!ctxRef.current) return
      analyser.getByteTimeDomainData(samples)
      let peak = 0
      for (const x of samples) peak = Math.max(peak, Math.abs(x - 128) / 128)
      setVolume(Math.min(1, peak * 2))
      rafRef.current = requestAnimationFrame(tick)
    }
    rafRef.current = requestAnimationFrame(tick)

    // ponytail: ScriptProcessorNode is deprecated but universally available;
    // move to an AudioWorklet when a second in-browser processor exists.
    const proc = ctx.createScriptProcessor(AUDIO.frameSize, 1, 1)
    processorRef.current = proc
    const ratio = ctx.sampleRate / AUDIO.sampleRate
    proc.onaudioprocess = (e) => {
      const ws = wsRef.current
      if (ws?.readyState !== WebSocket.OPEN) return
      const input = e.inputBuffer.getChannelData(0)
      const outLength = Math.floor(input.length / ratio)
      if (outLength <= 0) return
      const out = new Int16Array(outLength)
      for (let i = 0; i < outLength; i++) {
        // Average the source window instead of point-sampling: a plain
        // nearest-neighbour pick aliases badly at 48k→16k and made speech
        // noticeably harder for the ASR stage to read.
        const start = Math.floor(i * ratio)
        const end = Math.min(input.length, Math.floor((i + 1) * ratio))
        let sum = 0
        let count = 0
        for (let j = start; j < end; j++) {
          sum += input[j] ?? 0
          count++
        }
        const sample = count > 0 ? sum / count : 0
        // Clamp to the int16 range before rounding; the old code could emit
        // 32768, which wraps to -32768 and clicks.
        out[i] = Math.max(-32768, Math.min(32767, Math.round(sample * 32767)))
      }
      ws.send(out.buffer)
    }
    src.connect(proc)
    // Silent sink keeps the processor pulling without echoing the mic to
    // the speakers.
    const sink = ctx.createGain()
    sink.gain.value = 0
    proc.connect(sink)
    sink.connect(ctx.destination)
  }, [])

  const start = useCallback(async () => {
    if (wsRef.current) return // already in a room
    const session = ++sessionRef.current
    setError(null)
    setHeard(null)
    setReply(null)
    setState("connecting")

    // Warm the GPU containers as the room opens so the first utterance does
    // not pay the cold-start cost.
    void fetch(`${API_URL}/api/v1/warm`, { method: "POST" }).catch(() => {})

    // Open the microphone FIRST. Previously the socket connected and the
    // server started its listening window while getUserMedia was still
    // showing a permission prompt — the room was live but deaf, which is
    // exactly the "connects but never listens" symptom.
    try {
      await startMic()
    } catch {
      setError("microphone unavailable — check browser permissions")
      setState("idle")
      stopMic()
      return
    }
    if (session !== sessionRef.current) {
      stopMic() // stopped while the permission prompt was open
      return
    }

    const ws = new WebSocket(
      wsURL("/api/v1/voice/session", {
        provider,
        ...(llm ? { llm } : {}),
      })
    )
    ws.binaryType = "arraybuffer"
    wsRef.current = ws

    ws.onopen = () => {
      // Re-assert the mode on connect: covers a mode change that landed
      // while the socket was still opening.
      ws.send(JSON.stringify({ type: "config", provider, ...(llm && { llm }) }))
      // Replay a hold that was pressed during the handshake.
      if (holdRef.current)
        ws.send(JSON.stringify({ type: "hold", active: true }))
    }

    ws.onmessage = (e) => {
      if (typeof e.data !== "string") {
        playReply(e.data as ArrayBuffer)
        return
      }
      let msg: ServerMessage
      try {
        msg = JSON.parse(e.data) as ServerMessage
      } catch {
        return // ignore malformed frames rather than throwing in the handler
      }
      switch (msg.type) {
        case "room":
          setRoom(msg.id)
          break
        case "state":
          setState(msg.value === "ended" ? "idle" : msg.value)
          break
        case "reply":
          if (msg.heard !== undefined) setHeard(msg.heard)
          if (msg.reply !== undefined) setReply(msg.reply)
          break
        case "error":
          setError(msg.message)
          break
      }
    }

    ws.onerror = () => {
      // onerror fires before onclose; the message is set here and the
      // cleanup happens in onclose so both paths converge.
      setError("voice session connection failed")
    }

    ws.onclose = () => {
      if (wsRef.current === ws) wsRef.current = null
      holdRef.current = false
      stopPlayback()
      stopMic()
      setRoom(null)
      setHolding(false)
      setState("idle")
    }
  }, [llm, playReply, provider, startMic, stopMic, stopPlayback])

  // Push-to-talk. The intent is recorded locally first so the button always
  // responds, even if the socket is still connecting.
  const holdStart = useCallback(() => {
    holdRef.current = true
    setHolding(true)
    sendControl({ type: "hold", active: true })
  }, [sendControl])

  const holdEnd = useCallback(() => {
    if (!holdRef.current) return
    holdRef.current = false
    setHolding(false)
    sendControl({ type: "flush" })
  }, [sendControl])

  // Follow the mode dropdown without dropping a live room.
  useEffect(() => {
    sendControl({ type: "config", provider, ...(llm && { llm }) })
  }, [llm, provider, sendControl])

  // Release the socket, microphone and audio element on unmount. Without
  // this the mic indicator stayed on after navigating away.
  useEffect(() => {
    return () => {
      sessionRef.current += 1
      wsRef.current?.close(1000, "component unmounted")
      wsRef.current = null
      stopPlayback()
      stopMic()
    }
  }, [stopMic, stopPlayback])

  return {
    state,
    volume,
    room,
    heard,
    reply,
    error,
    holding,
    start,
    stop,
    holdStart,
    holdEnd,
  }
}
