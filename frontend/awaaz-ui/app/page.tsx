"use client";

import { useEffect, useRef, useState } from "react";
import {
  ChevronDownIcon,
  CheckIcon,
  MessageSquareIcon,
  MicIcon,
} from "lucide-react";
import { Button } from "@/components/ui/button";
import { Thread } from "@/components/assistant-ui/elements/thread.aui";
import {
  VoiceOrb,
  type VoiceOrbState,
} from "@/components/assistant-ui/elements/voice";
import {
  AwaazRuntimeProvider,
  type Provider,
} from "./awaaz-runtime";

const API_URL = process.env.NEXT_PUBLIC_API_URL ?? "http://localhost:18080";

const STATUS_LABEL: Record<VoiceOrbState, string> = {
  idle: "Tap to start",
  listening: "Listening",
  connecting: "Thinking",
  speaking: "Speaking",
  muted: "Muted",
};

type Mode = "ab-voice" | "ab-voice-sxl" | "ab-chat" | "sarvam-voice" | "sarvam-chat";

const MODES: {
  id: Mode;
  label: string;
  group: string;
  provider: Provider;
  voice: boolean;
  llm?: "sarvam";
}[] = [
  { id: "ab-voice-sxl", label: "Voice · Sarvam LLM", group: "Awaaz", provider: "awaaz", voice: true, llm: "sarvam" },
  { id: "ab-voice", label: "Voice · Qwen LLM", group: "Awaaz", provider: "awaaz", voice: true },
  { id: "ab-chat", label: "Chat", group: "Awaaz", provider: "awaaz", voice: false },
  { id: "sarvam-voice", label: "Voice", group: "Sarvam", provider: "sarvam", voice: true },
  { id: "sarvam-chat", label: "Chat", group: "Sarvam", provider: "sarvam", voice: false },
];

function modeInfo(mode: Mode) {
  return MODES.find((m) => m.id === mode)!;
}

// Minimal dropdown: current mode + grouped menu. Escape and outside-click close.
function ModeMenu({
  mode,
  setMode,
}: {
  mode: Mode;
  setMode: (m: Mode) => void;
}) {
  const [open, setOpen] = useState(false);
  const ref = useRef<HTMLDivElement>(null);

  useEffect(() => {
    if (!open) return;
    const onDoc = (e: MouseEvent) => {
      if (!ref.current?.contains(e.target as Node)) setOpen(false);
    };
    const onKey = (e: KeyboardEvent) => {
      if (e.key === "Escape") setOpen(false);
    };
    document.addEventListener("mousedown", onDoc);
    document.addEventListener("keydown", onKey);
    return () => {
      document.removeEventListener("mousedown", onDoc);
      document.removeEventListener("keydown", onKey);
    };
  }, [open]);

  const info = modeInfo(mode);
  const groups = [...new Set(MODES.map((m) => m.group))];

  return (
    <div ref={ref} className="relative">
      <button
        onClick={() => setOpen((o) => !o)}
        aria-haspopup="menu"
        aria-expanded={open}
        className="flex items-center gap-2 rounded-full border border-white/10 bg-white/[0.028] py-1.5 pr-3 pl-4 text-[13px] text-white/80 transition-colors hover:border-white/25"
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
          role="menu"
          className="absolute right-0 z-20 mt-2 min-w-60 rounded-2xl border border-white/10 bg-[#141414] p-1.5 shadow-2xl shadow-black/60"
        >
          {groups.map((g) => (
            <div key={g} className="p-1">
              <p className="px-2 pt-1 pb-1.5 text-[10px] font-medium tracking-[0.2em] text-white/30 uppercase">
                {g}
              </p>
              {MODES.filter((m) => m.group === g).map((m) => (
                <button
                  key={m.id}
                  role="menuitem"
                  onClick={() => {
                    setMode(m.id);
                    setOpen(false);
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
  );
}

export default function Page() {
  const [mode, setMode] = useState<Mode>("ab-voice-sxl");
  const [orb, setOrb] = useState<VoiceOrbState>("idle");
  const [volume, setVolume] = useState(0);
  const [room, setRoom] = useState<string | null>(null);
  const [heard, setHeard] = useState<string | null>(null);
  const [reply, setReply] = useState<string | null>(null);
  const [voiceError, setVoiceError] = useState<string | null>(null);
  const [facts, setFacts] = useState<{ id: number; text: string }[]>([]);
  const [factInput, setFactInput] = useState("");
  const [holding, setHolding] = useState(false);

  const wsRef = useRef<WebSocket | null>(null);
  const streamRef = useRef<MediaStream | null>(null);
  const ctxRef = useRef<AudioContext | null>(null);
  const warmedRef = useRef(false);

  const { provider, voice, llm } = modeInfo(mode);

  useEffect(() => {
    void refreshFacts();
  }, []);

  // Preload cold GPU containers once, when voice becomes the active stage.
  useEffect(() => {
    if (!voice || warmedRef.current) return;
    warmedRef.current = true;
    void fetch(`${API_URL}/api/v1/warm`, { method: "POST" }).catch(() => {});
  }, [voice]);

  // A live room follows the mode dropdown without dropping the session.
  useEffect(() => {
    if (wsRef.current?.readyState === WebSocket.OPEN) {
      wsRef.current.send(JSON.stringify({ type: "config", provider, ...(llm && { llm }) }));
    }
  }, [provider, llm]);

  async function refreshFacts() {
    try {
      const res = await fetch(`${API_URL}/api/v1/memory`);
      if (res.ok) setFacts((await res.json()).facts ?? []);
    } catch {
      // Panel stays empty when the sidecar is down; chat is unaffected.
    }
  }

  async function remember() {
    const text = factInput.trim();
    if (!text) return;
    setFactInput("");
    await fetch(`${API_URL}/api/v1/memory`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ text }),
    });
    await refreshFacts();
  }

  async function forget(text: string) {
    await fetch(`${API_URL}/api/v1/memory/forget`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ text }),
    });
    await refreshFacts();
  }

  function stopMic() {
    streamRef.current?.getTracks().forEach((t) => t.stop());
    streamRef.current = null;
    void ctxRef.current?.close().catch(() => {});
    ctxRef.current = null;
    setVolume(0);
  }

  function endSession() {
    wsRef.current?.close();
    wsRef.current = null;
    stopMic();
    setRoom(null);
    setHolding(false);
    setOrb("idle");
  }

  // Push-to-talk inside a room: holding suspends the server's silence flush,
  // releasing sends the turn immediately — no VAD timeout in the path, so a
  // mid-thought pause can never cut the turn.
  function holdStart(e: React.PointerEvent<HTMLButtonElement>) {
    e.currentTarget.setPointerCapture(e.pointerId);
    if (wsRef.current?.readyState === WebSocket.OPEN) {
      wsRef.current.send(JSON.stringify({ type: "hold", active: true }));
      setHolding(true);
    }
  }

  function holdEnd() {
    if (!holding) return;
    setHolding(false);
    if (wsRef.current?.readyState === WebSocket.OPEN) {
      wsRef.current.send(JSON.stringify({ type: "flush" }));
    }
  }

  async function startSession() {
    setVoiceError(null);
    setHeard(null);
    setReply(null);
    // Warm the GPU containers as the room opens: by the time the first
    // utterance lands, whisper and parler are usually already loaded.
    void fetch(`${API_URL}/api/v1/warm`, { method: "POST" }).catch(() => {});
    const proto = API_URL.startsWith("https") ? "wss" : "ws";
    // provider+llm ride the URL query: the server reads them at connect, so
    // there is no race with the config frame (which only covers mid-session
    // switches). Without this the room silently falls back to qwen.
    const qs = new URLSearchParams({ provider, ...(llm && { llm }) }).toString();
    const ws = new WebSocket(
      `${proto}://${new URL(API_URL).host}/api/v1/voice/session?${qs}`,
    );
    ws.binaryType = "arraybuffer";
    ws.onopen = () => {
      // Re-assert the mode on every connect: covers reconnects and any
      // mode change that landed while the socket was still opening.
      ws.send(JSON.stringify({ type: "config", provider, ...(llm && { llm }) }));
    };
    ws.onmessage = (e) => {
      if (typeof e.data === "string") {
        const m = JSON.parse(e.data);
        if (m.type === "room") setRoom(m.id);
        else if (m.type === "state")
          setOrb(m.value === "thinking" ? "connecting" : m.value === "ended" ? "idle" : m.value);
        else if (m.type === "reply") {
          setHeard(m.heard);
          setReply(m.reply);
        } else if (m.type === "error") setVoiceError(m.message);
      } else {
        const url = URL.createObjectURL(new Blob([e.data], { type: "audio/wav" }));
        const releaseGuard = () => {
          URL.revokeObjectURL(url);
          if (wsRef.current?.readyState === WebSocket.OPEN) {
            wsRef.current.send(JSON.stringify({ type: "played" }));
          }
        };
        const audio = new Audio(url);
        audio.onended = releaseGuard;
        audio.onerror = () => {
          setVoiceError("could not play reply");
          setOrb("idle");
          releaseGuard();
        };
        void audio.play().catch(() => {
          setVoiceError("could not play reply");
          setOrb("idle");
          releaseGuard();
        });
      }
    };
    ws.onclose = () => {
      setRoom(null);
      setOrb("idle");
      stopMic();
    };
    ws.onerror = () => setVoiceError("session connection failed");
    wsRef.current = ws;

    try {
      const stream = await navigator.mediaDevices.getUserMedia({ audio: true });
      streamRef.current = stream;
      const ctx = new AudioContext();
      ctxRef.current = ctx;
      const src = ctx.createMediaStreamSource(stream);

      const analyser = ctx.createAnalyser();
      analyser.fftSize = 256;
      src.connect(analyser);
      const data = new Uint8Array(analyser.frequencyBinCount);
      const tick = () => {
        if (!ctxRef.current) return;
        analyser.getByteTimeDomainData(data);
        let peak = 0;
        for (const x of data) peak = Math.max(peak, Math.abs(x - 128) / 128);
        setVolume(Math.min(1, peak * 2));
        requestAnimationFrame(tick);
      };
      tick();

      // ponytail: ScriptProcessorNode is deprecated but universal; AudioWorklet
      // when a second in-browser audio processor ever exists.
      const proc = ctx.createScriptProcessor(4096, 1, 1);
      proc.onaudioprocess = (e) => {
        if (wsRef.current?.readyState !== WebSocket.OPEN) return;
        const inp = e.inputBuffer.getChannelData(0);
        const out = new Int16Array(
          Math.floor((inp.length * 16000) / ctx.sampleRate),
        );
        for (let i = 0; i < out.length; i++) {
          const s = inp[Math.floor((i * ctx.sampleRate) / 16000)];
          out[i] = Math.max(-32768, Math.min(32767, Math.round(s * 32768)));
        }
        wsRef.current.send(out.buffer);
      };
      src.connect(proc);
      const sink = ctx.createGain();
      sink.gain.value = 0; // silent sink: keeps the processor pulling
      proc.connect(sink);
      sink.connect(ctx.destination);
    } catch {
      setVoiceError("microphone unavailable");
      endSession();
    }
  }

  const busy = orb === "listening" || orb === "connecting" || orb === "speaking";
  const live = orb === "listening" || orb === "speaking";

  const voiceStage = (
    <section className="flex min-h-[calc(100svh-11rem)] w-full flex-col items-center justify-center text-center md:min-h-0">
      <div className="flex items-center gap-2" aria-live="polite">
        <span
          className={`size-2 rounded-full ${
            live ? "ab-live-dot" : busy ? "animate-pulse bg-amber-400" : "bg-white/30"
          }`}
        />
        <span
          className={`text-xs font-medium tracking-[0.25em] uppercase ${
            busy ? "voice-busy" : "text-white/50"
          }`}
        >
          {STATUS_LABEL[orb]}
        </span>
      </div>

      <div className="relative my-2 flex items-center justify-center py-4">
        <div className="ab-orb-glow absolute size-72 rounded-full" aria-hidden />
        <VoiceOrb
          state={orb}
          volume={volume}
          className="relative size-48 md:size-60"
        />
      </div>

      {/* Fixed-height slot: invitation and transcript swap without
          shifting the session button. */}
      <div className="flex min-h-32 w-full flex-col items-center justify-center gap-1.5 px-2 pb-6">
        {(heard || reply) && (
          <>
            {heard && (
              <p key={`h-${heard}`} className="voice-rise text-base text-white/45">
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
          </>
        )}
        {!heard && !reply && orb === "idle" && (
          <>
            <p className="text-2xl font-medium tracking-tight text-[#fafafa] md:text-3xl">
              हलो बोलिए
            </p>
            <p className="ab-grad-text pt-0.5 text-2xl font-medium tracking-tight md:text-3xl">
              హలో చెప్పండి
            </p>
            <p className="pt-1.5 text-xs text-white/40">
              Open a room, hold to talk — release to send. Pauses never cut you off.
            </p>
          </>
        )}
        {voiceError && <p className="text-sm text-red-400">{voiceError}</p>}
      </div>

      <div className="relative">
        <div className="ab-pill-glow absolute inset-x-4 -bottom-2 h-4 rounded-full" aria-hidden />
        {!room ? (
          <button
            onClick={startSession}
            className="relative flex h-12 items-center gap-2 rounded-full bg-white px-8 text-sm font-medium text-[#0c0c0c] transition-[filter,transform] hover:brightness-95 active:scale-95"
          >
            <MicIcon className="size-4" /> Talk
          </button>
        ) : (
          <div className="flex items-center gap-3">
            <button
              onPointerDown={holdStart}
              onPointerUp={holdEnd}
              onPointerCancel={holdEnd}
              className={`relative flex h-12 items-center gap-2 rounded-full px-8 text-sm font-medium transition-[filter,transform] active:scale-95 ${
                holding
                  ? "ab-grad text-[#0c0c0c]"
                  : "bg-white text-[#0c0c0c] hover:brightness-95"
              }`}
            >
              <MicIcon className="size-4" />
              {holding ? "Release to send" : "Hold to talk"}
            </button>
            <button
              onClick={endSession}
              className="text-sm text-white/45 transition-colors hover:text-white"
            >
              End
            </button>
          </div>
        )}
      </div>
    </section>
  );

  const chatStage = (
    <AwaazRuntimeProvider provider={provider}>
      <section className="h-[70svh] min-h-0 w-full md:h-full md:flex-1">
        <div className="h-full overflow-hidden rounded-3xl border ab-hairline bg-white/[0.02]">
          <Thread />
        </div>
      </section>
    </AwaazRuntimeProvider>
  );

  return (
    <div className="dark flex min-h-svh flex-col bg-[#0c0c0c] font-sans text-white md:h-svh md:overflow-hidden">
      <header className="flex h-12 shrink-0 items-center justify-between border-b ab-hairline px-5">
        <a href="#" aria-label="Awaaz home" className="text-sm font-medium tracking-tight">
          A<span className="ab-grad-text">waaz</span>
        </a>
        <ModeMenu mode={mode} setMode={setMode} />
      </header>

      <main className="mx-auto flex w-full max-w-6xl flex-1 min-h-0 flex-col px-6 py-3">
        {voice ? voiceStage : chatStage}
      </main>

      <footer className="shrink-0 border-t ab-hairline">
        <div className="mx-auto flex w-full max-w-6xl flex-col items-center gap-2 px-6 py-3 sm:flex-row">
          <div className="flex w-full gap-2 sm:w-auto sm:min-w-64">
            <input
              value={factInput}
              onChange={(e) => setFactInput(e.target.value)}
              onKeyDown={(e) => e.key === "Enter" && remember()}
              placeholder="Remember this..."
              className="min-w-0 flex-1 rounded-full border ab-hairline bg-white/[0.02] px-4 py-1.5 text-sm text-[#efefef] outline-none placeholder:text-white/30 focus:border-white/30"
            />
            <Button
              size="sm"
              onClick={remember}
              className="h-8 rounded-full bg-white text-[#0c0c0c] hover:bg-white/90"
            >
              Save
            </Button>
          </div>
          <ul className="flex max-h-16 w-full flex-1 flex-wrap gap-1.5 overflow-y-auto sm:justify-end">
            {facts.map((f) => (
              <li
                key={f.id}
                className="voice-rise flex items-center gap-1.5 rounded-full border ab-hairline bg-white/[0.03] py-1 pr-1.5 pl-3 text-xs text-[#efefef]"
              >
                <span className="min-w-0">{f.text}</span>
                <button
                  onClick={() => forget(f.text)}
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
  );
}
