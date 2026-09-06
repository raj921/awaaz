"use client";

import { useEffect, useMemo, useRef, type ReactNode } from "react";
import {
  AssistantRuntimeProvider,
  useLocalRuntime,
  type ChatModelAdapter,
} from "@assistant-ui/react";

export type Provider = "awaaz" | "sarvam";

const API_URL = process.env.NEXT_PUBLIC_API_URL ?? "http://localhost:18080";

export function AwaazRuntimeProvider({
  provider,
  children,
}: Readonly<{ provider: Provider; children: ReactNode }>) {
  // Read at run time so switching provider never resets the thread.
  const providerRef = useRef(provider);
  useEffect(() => {
    providerRef.current = provider;
  }, [provider]);

  const runtime = useLocalRuntime(
    useMemo<ChatModelAdapter>(
      () => ({
        async run({ messages, abortSignal }) {
          const res = await fetch(`${API_URL}/api/v1/chat`, {
            method: "POST",
            headers: { "Content-Type": "application/json" },
            body: JSON.stringify({
              messages: messages.map((m) => ({
                role: m.role,
                content: m.content
                  .filter((c) => c.type === "text")
                  .map((c) => c.text)
                  .join("\n"),
              })),
              max_tokens: 50,
              provider: providerRef.current,
            }),
            signal: abortSignal,
          });
          const data = await res.json();
          if (!res.ok)
            throw new Error(data?.error?.message ?? `HTTP ${res.status}`);
          return { content: [{ type: "text", text: data.reply }] };
        },
      }),
      [],
    ),
  );
  return (
    <AssistantRuntimeProvider runtime={runtime}>
      {children}
    </AssistantRuntimeProvider>
  );
}
