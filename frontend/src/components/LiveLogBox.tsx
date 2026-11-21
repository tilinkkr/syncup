"use client";

import { useEffect, useRef, useState } from "react";
import { Check, Copy } from "lucide-react";
import type { LogEntry } from "@/lib/types";

export const formatLogLine = (l: LogEntry) => `[${l.ts}] ${l.level.padEnd(6)} [${l.source}] ${l.message}`;

const SOURCE_TONE: Record<string, string> = {
  RTC: "text-zinc-500",
  ASR: "text-amber-700",
  TTS: "text-amber-600",
  TRIAGE: "text-zinc-800",
  DB: "text-zinc-800",
  ROUTE: "text-emerald-700",
};

function tone(l: LogEntry): string {
  if (l.level === "WARN" || l.message.startsWith("DEBUNKED")) return "text-rose-600";
  if (l.source === "ROUTE" && l.level === "ACTION") return "text-emerald-700 font-semibold";
  if (l.level === "ACTION") return "text-zinc-900 font-semibold";
  return "text-zinc-800";
}

/** Compact live pipeline log with one-click Copy (for judges / debugging). */
export function LiveLogBox({ logs }: { logs: LogEntry[] }) {
  const [copied, setCopied] = useState(false);
  const scrollRef = useRef<HTMLDivElement>(null);

  useEffect(() => {
    const el = scrollRef.current;
    if (el) el.scrollTop = el.scrollHeight;
  }, [logs.length]);

  const copy = async () => {
    const text = logs.map(formatLogLine).join("\n");
    try {
      await navigator.clipboard.writeText(text);
    } catch {
      const ta = document.createElement("textarea"); // non-secure-context fallback
      ta.value = text;
      document.body.appendChild(ta);
      ta.select();
      document.execCommand("copy");
      ta.remove();
    }
    setCopied(true);
    setTimeout(() => setCopied(false), 2000);
  };

  return (
    <section className="flex h-44 min-h-0 flex-col overflow-hidden rounded-xl border border-[#E4E4E7] bg-white shadow-sm lg:h-full">
      <header className="flex shrink-0 items-center gap-2 border-b border-yellow-200 bg-[#FEFCE8] px-3 py-1.5">
        <span className={`h-2 w-2 rounded-full ${logs.length ? "animate-pulse bg-emerald-500" : "bg-zinc-300"}`} />
        <h3 className="text-[13px] font-bold text-[#18181B]">Live Pipeline Logs</h3>
        <span className="rounded-full bg-white px-1.5 text-[11px] tabular-nums text-zinc-500">{logs.length}</span>
        <button
          onClick={copy}
          disabled={!logs.length}
          className={`ml-auto flex items-center gap-1 rounded-full px-3 py-1 text-[12px] font-bold transition disabled:opacity-40 ${
            copied ? "bg-emerald-600 text-white" : "bg-[#FACC15] text-[#18181B] hover:bg-yellow-300"
          }`}
        >
          {copied ? <Check size={12} /> : <Copy size={12} />}
          {copied ? "Copied!" : "Copy"}
        </button>
      </header>
      <div ref={scrollRef} className="min-h-0 flex-1 overflow-y-auto px-3 py-1.5 font-mono text-[10.5px] leading-[1.55]">
        {logs.length === 0 ? (
          <p className="text-zinc-400">Waiting for pipeline events…</p>
        ) : (
          logs.map((l) => (
            <div key={l.id} className="break-words">
              <span className="text-zinc-400">{l.ts.slice(0, 8)}</span>{" "}
              <span className={`font-semibold ${SOURCE_TONE[l.source] ?? "text-zinc-500"}`}>{l.source}</span>{" "}
              <span className={tone(l)}>{l.message}</span>
            </div>
          ))
        )}
      </div>
    </section>
  );
}
