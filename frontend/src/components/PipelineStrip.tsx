"use client";

import { ChevronRight } from "lucide-react";
import type { AgentState, LatencyMetrics, LogEntry, SessionStatus, Tuning } from "@/lib/types";

const STAGES = [
  { key: "voice", title: "Voice" },
  { key: "asr", title: "Agora ASR" },
  { key: "llm", title: "LLM" },
  { key: "db", title: "Maintenance logs" },
  { key: "tts", title: "Murf voice" },
  { key: "ticket", title: "Ticket" },
] as const;

const SOURCE_TO_STAGE: Record<string, string> = { ASR: "asr", TRIAGE: "llm", DB: "db", TTS: "tts", ROUTE: "ticket" };

function toMs(ts: string): number {
  const [h, m, rest] = ts.split(":");
  return (Number(h) * 3600 + Number(m) * 60 + Number(rest)) * 1000;
}

function activeStage(agentState: AgentState, logs: LogEntry[], status?: SessionStatus): string | null {
  // Most recent pipeline event wins for ~2.5 s (live calls and the Demo Sim alike).
  const last = [...logs].reverse().find((l) => SOURCE_TO_STAGE[l.source]);
  if (last) {
    const d = new Date();
    const nowMs = ((d.getHours() * 60 + d.getMinutes()) * 60 + d.getSeconds()) * 1000 + d.getMilliseconds();
    if (Math.abs(nowMs - toMs(last.ts)) < 2500) return SOURCE_TO_STAGE[last.source];
  }
  if (status === "ROUTED") return "ticket";
  if (agentState === "listening") return "voice";
  if (agentState === "thinking") return "llm";
  if (agentState === "speaking") return "tts";
  return null;
}

/** One-line "how it works" strip: the live stage lights up yellow. Audio never touches our server. */
export function PipelineStrip({
  agentState,
  logs,
  status,
  latency,
  tuning,
  tick,
}: {
  agentState: AgentState;
  logs: LogEntry[];
  status?: SessionStatus;
  latency: LatencyMetrics;
  tuning?: Tuning | null;
  tick: number; // forces re-evaluation of the time window
}) {
  void tick;
  const active = activeStage(agentState, logs, status);

  return (
    <section aria-label="How SyncUp works" className="flex shrink-0 flex-wrap items-center gap-x-3 gap-y-1.5">
      <ol className="flex flex-wrap items-center gap-1">
        {STAGES.map((s, i) => {
          const on = active === s.key;
          const done = s.key === "ticket" && status === "ROUTED";
          return (
            <li key={s.key} className="flex items-center gap-1">
              <span
                className={`rounded-full px-2.5 py-0.5 text-xs font-medium transition-colors duration-300 ${
                  on ? "bg-yellow-400 text-stone-900" : done ? "bg-green-100 text-green-700" : "bg-stone-100 text-stone-500"
                }`}
              >
                {s.title}
              </span>
              {i < STAGES.length - 1 && <ChevronRight size={12} className="text-stone-300" />}
            </li>
          );
        })}
      </ol>
      <span className="ml-auto text-xs text-stone-500" title={tuning ? `LLM temp ${tuning.temperature} · Murf rate ${tuning.rate} pitch ${tuning.pitch} · VAD ${tuning.vad_threshold} · silence ${tuning.silence_ms} ms` : undefined}>
        Response time{" "}
        <span className={`font-semibold tabular-nums ${latency.e2e ? (latency.e2e < 900 ? "text-green-600" : "text-red-600") : "text-stone-400"}`}>
          {latency.e2e ? `${latency.e2e} ms` : "—"}
        </span>
      </span>
    </section>
  );
}
