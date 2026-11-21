"use client";

import { useEffect, useMemo, useRef, useState } from "react";
import {
  ArrowRight,
  BatteryFull,
  BellOff,
  BellRing,
  CheckCircle2,
  Database,
  Loader2,
  Mic,
  MicOff,
  Phone,
  PhoneCall,
  PhoneOff,
  RotateCcw,
  Signal,
  Smartphone,
  TriangleAlert,
} from "lucide-react";
import type { AudioLevels } from "@/hooks/useAgoraSession";
import { useRingtone } from "@/hooks/useRingtone";
import type { LanguageOption } from "@/lib/config";
import type { AgentState, AssetContext, CallPhase, DemoStage, Escalation, LatencyMetrics, SessionStatus, Transcript } from "@/lib/types";
import { AudioVisualizer } from "./AudioVisualizer";
import { ConversationFeed } from "./ConversationFeed";
import { Spotlight } from "./Spotlight";

export type GuideTarget = "qr" | "start" | "listen" | "finish" | "answer" | "confirm" | "done";

interface Props {
  lang: LanguageOption;
  scenario: string;
  phase: CallPhase;
  micMuted: boolean;
  error: string | null;
  simulated: boolean;
  agentState: AgentState;
  transcripts: Transcript[];
  latency: LatencyMetrics;
  getLevels: () => AudioLevels;
  assetContext: AssetContext | null;
  guardMuting: boolean;
  demoStage: DemoStage;
  status: SessionStatus | undefined;
  target: GuideTarget;
  escalation: Escalation | null;
  engineerName: string;
  engineerRole: string;
  ticketId: string | null;
  priority: string | null;
  engJoining: boolean;
  onCall: boolean;
  getEngineerLevel: () => number;
  onScanQr: () => void;
  onStart: () => void;
  onStop: () => void;
  onToggleMic: () => void;
  onFinish: () => void;
  onAnswer: (language: string) => void;
  onDecline: () => void;
  onConfirm: () => void;
  onHangUp: () => void;
  onRestart: () => void;
}

const fmt = (s: number) => `${String(Math.floor(s / 60)).padStart(2, "0")}:${String(Math.floor(s % 60)).padStart(2, "0")}`;

function useClock(running: boolean, since?: number | null) {
  const [now, setNow] = useState(Date.now() / 1000);
  const startRef = useRef<number | null>(null);
  useEffect(() => {
    if (!running) {
      startRef.current = null;
      return;
    }
    startRef.current = since ?? Date.now() / 1000;
    const id = setInterval(() => setNow(Date.now() / 1000), 1000);
    return () => clearInterval(id);
  }, [running, since]);
  return running && startRef.current ? fmt(Math.max(0, now - startRef.current)) : "00:00";
}

/** Deterministic QR-style pattern (decorative): 25x25 modules with three finder squares. */
function QrPattern() {
  const cells = useMemo(() => {
    const n = 25;
    const out: [number, number][] = [];
    let seed = 891;
    const rnd = () => ((seed = (seed * 9301 + 49297) % 233280) / 233280);
    const finder = (x: number, y: number) =>
      [[0, 0], [n - 7, 0], [0, n - 7]].some(([fx, fy]) => x >= fx && x < fx + 7 && y >= fy && y < fy + 7);
    for (let y = 0; y < n; y++)
      for (let x = 0; x < n; x++) {
        if (finder(x, y)) {
          const [fx, fy] = x < 7 && y < 7 ? [0, 0] : x >= n - 7 ? [n - 7, 0] : [0, n - 7];
          const dx = x - fx;
          const dy = y - fy;
          const ring = dx === 0 || dy === 0 || dx === 6 || dy === 6;
          const core = dx >= 2 && dx <= 4 && dy >= 2 && dy <= 4;
          if (ring || core) out.push([x, y]);
        } else if (rnd() > 0.52) out.push([x, y]);
      }
    return out;
  }, []);
  return (
    <svg viewBox="0 0 25 25" className="h-full w-full" shapeRendering="crispEdges" aria-hidden>
      {cells.map(([x, y]) => (
        <rect key={`${x}-${y}`} x={x} y={y} width="1" height="1" fill="#18181B" />
      ))}
    </svg>
  );
}

/** Left pane: a realistic phone. Worker app (QR -> voice triage), then the lead engineer's device (ringing -> call). */
export function WorkerPane(p: Props) {
  const live = p.phase === "live";
  const busy = p.phase === "connecting" || p.phase === "ending";
  const engineerDevice = p.demoStage === "ENGINEER_RINGING" || p.demoStage === "ENGINEER_CONNECTED" || p.demoStage === "DISPATCH_CONFIRMED";
  const [scanning, setScanning] = useState(false);
  const [ringMuted, setRingMuted] = useState(false);
  const [engLang, setEngLang] = useState("en-IN");
  const [recent, setRecent] = useState(false);
  const lastId = p.transcripts[p.transcripts.length - 1]?.id;
  const workerClock = useClock(live);
  const call = p.escalation;
  const engConnected = p.demoStage === "ENGINEER_CONNECTED" || p.demoStage === "DISPATCH_CONFIRMED";
  const engEnded = !!call && (call.status === "completed" || call.status === "failed");
  const engClock = useClock(engConnected && !engEnded, call?.connected_at ?? null);
  const feedRef = useRef<HTMLDivElement>(null);

  useRingtone(p.demoStage === "ENGINEER_RINGING" && !ringMuted);

  useEffect(() => {
    if (!lastId || live) return;
    setRecent(true);
    const t = setTimeout(() => setRecent(false), 1600);
    return () => clearTimeout(t);
  }, [lastId, live]);

  useEffect(() => {
    feedRef.current?.scrollTo({ top: feedRef.current.scrollHeight, behavior: "smooth" });
  }, [call?.transcripts.length]);

  const scan = () => {
    if (scanning) return;
    setScanning(true);
    setTimeout(() => {
      setScanning(false);
      p.onScanQr();
    }, 650);
  };

  const showQr = p.demoStage === "QR_READY" && !live && !busy;
  const awaiting = p.status === "AWAITING_APPROVAL";

  return (
    <aside className="flex shrink-0 flex-col items-center gap-2 bg-[#FAFAF9] p-3 lg:min-h-0 lg:w-[40%] lg:shrink lg:border-r lg:border-[#E4E4E7] lg:p-5">
      {/* Phone hardware frame */}
      <div className="relative flex h-[720px] w-[380px] lg:h-[min(780px,100%)] lg:min-h-[640px] max-w-full flex-col overflow-hidden rounded-[42px] border-[10px] border-zinc-900 bg-white shadow-2xl">
        {/* Status bar + dynamic island */}
        <div className={`relative flex h-9 shrink-0 items-center justify-between px-6 text-[12px] font-semibold ${engineerDevice ? "bg-[#18181B] text-white" : "bg-[#FACC15] text-[#18181B]"}`}>
          <span>9:41</span>
          <span className="absolute left-1/2 top-1.5 h-6 w-24 -translate-x-1/2 rounded-full bg-zinc-900 ring-1 ring-zinc-700" aria-hidden />
          <span className="flex items-center gap-1">
            <Signal size={13} strokeWidth={2.5} />
            <span className="text-[10.5px] font-bold">5G</span>
            <BatteryFull size={16} strokeWidth={2} />
          </span>
        </div>

        {/* App header */}
        {engineerDevice ? (
          <div className="flex shrink-0 items-center gap-2.5 bg-[#18181B] px-4 pb-3 pt-1 text-white">
            <div className="grid h-9 w-9 place-items-center rounded-full bg-[#FACC15] text-[12px] font-black text-[#18181B]">AM</div>
            <div className="min-w-0 flex-1 leading-tight">
              <p className="text-[15px] font-black tracking-tight">Engineer Device • {p.engineerName}</p>
              <p className="truncate text-[11.5px] text-zinc-300">{p.engineerRole} • Electrical & Controls</p>
            </div>
          </div>
        ) : (
          <div className="flex shrink-0 items-center gap-2.5 bg-[#FACC15] px-4 pb-3 pt-1">
            <div className="grid h-9 w-9 place-items-center rounded-full bg-[#18181B] text-[12px] font-black text-[#FACC15]">RK</div>
            <div className="min-w-0 flex-1 leading-tight">
              <p className="text-[15px] font-black tracking-tight text-[#18181B]">SyncUp Worker App</p>
              <p className="truncate text-[11.5px] font-medium text-zinc-800">Ramesh K. • Shift B • {p.lang.code}</p>
            </div>
            <span className="flex shrink-0 items-center gap-1 rounded-full bg-white/75 px-2 py-0.5 text-[10.5px] font-semibold text-[#18181B]">
              {live && <span className="h-1.5 w-1.5 animate-pulse rounded-full bg-emerald-500" />}
              {live ? workerClock : p.simulated ? "Demo Sim" : showQr ? "Scan to start" : "Ready"}
            </span>
          </div>
        )}

        {/* ---------------------------------------------------------------- Screen A: clickable QR */}
        {showQr && (
          <div className="flex min-h-0 flex-1 flex-col items-center justify-center gap-4 bg-white px-6">
            <p className="text-center text-[13px] font-medium text-zinc-500">Point your camera at the machine&apos;s QR sticker</p>
            <Spotlight on={p.target === "qr" && !scanning} rounded="rounded-3xl" className="w-full">
              <button
                onClick={scan}
                aria-label="Click QR to simulate scan and start"
                className="group relative w-full rounded-3xl border border-[#E4E4E7] bg-white p-4 shadow-sm transition hover:shadow-md"
              >
                <div className="relative mx-auto aspect-square w-52 p-3">
                  {/* yellow scan frame corners */}
                  {["left-0 top-0 border-l-4 border-t-4", "right-0 top-0 border-r-4 border-t-4", "bottom-0 left-0 border-b-4 border-l-4", "bottom-0 right-0 border-b-4 border-r-4"].map((c) => (
                    <span key={c} className={`absolute h-8 w-8 rounded-sm border-[#FACC15] ${c}`} />
                  ))}
                  <QrPattern />
                  {scanning && <span className="absolute inset-x-1 h-1 animate-laser rounded-full bg-[#FACC15] shadow-[0_0_14px_4px_rgba(250,204,21,0.8)]" />}
                </div>
                <p className="mt-3 text-[15px] font-black text-[#18181B]">Bosch Pack-400 • {p.scenario}</p>
                <p className="text-[12.5px] font-semibold text-amber-600">{scanning ? "Scanning…" : "Click QR to Simulate Scan & Start"}</p>
              </button>
            </Spotlight>
            <a
              href={typeof window !== "undefined" ? window.location.href : "#"}
              target="_blank"
              rel="noreferrer"
              title="Open this page on a phone on the same Wi-Fi (use your laptop's LAN IP instead of localhost)"
              className="flex items-center gap-1 text-[12px] font-medium text-zinc-500 underline-offset-2 hover:text-[#18181B] hover:underline"
            >
              <Smartphone size={13} /> Open on Real Mobile
            </a>
          </div>
        )}

        {/* ---------------------------------------------------------------- Screen B: worker intake call */}
        {!showQr && !engineerDevice && (
          <div className="flex min-h-0 flex-1 flex-col gap-2.5 bg-white p-3">
            {p.assetContext && (
              <div className="flex shrink-0 items-center gap-2 rounded-xl border border-[#E4E4E7] px-3 py-2 text-[12px]">
                <span className="flex items-center gap-1 rounded-md bg-emerald-50 px-1.5 py-0.5 font-mono text-[10.5px] font-semibold text-emerald-700">
                  <Database size={10} /> {p.assetContext.maintenance_logs[0]?.log_id}
                </span>
                <span className="truncate text-zinc-600">
                  {p.assetContext.asset_id} • {p.assetContext.maintenance_logs[0]?.component} replaced {p.assetContext.maintenance_logs[0]?.date}
                </span>
              </div>
            )}
            <section className="flex min-h-0 flex-1 flex-col overflow-hidden rounded-2xl border border-yellow-200 bg-[#FEFCE8]">
              <div className="flex items-center justify-between px-3 pt-2 text-[10.5px] font-semibold text-amber-800">
                <span>Live {p.lang.short} voice</span>
                <span className="text-zinc-500">{p.latency.e2e ? `reply ${p.latency.e2e} ms` : "ARES ASR ↔ Murf Falcon 2.1"}</span>
              </div>
              <div className="px-2">
                <AudioVisualizer getLevels={p.getLevels} active={live} pulse={recent} />
              </div>
              <div className="flex min-h-0 flex-1 flex-col rounded-t-2xl bg-white">
                <ConversationFeed transcripts={p.transcripts} lang={p.lang} />
              </div>
            </section>

            {p.error && (
              <div className="flex gap-2 rounded-xl border border-rose-200 bg-rose-50 p-2 text-[12px] text-rose-700">
                <TriangleAlert size={14} className="mt-0.5 shrink-0" />
                <span className="line-clamp-2 break-words">{p.error}</span>
              </div>
            )}

            <div className="shrink-0 space-y-2">
              {live && p.guardMuting && <p className="text-center text-[11px] font-medium text-amber-700">Mic paused while SyncUp speaks (Echo Guard)</p>}
              {!p.simulated && (live || p.target === "finish") && (
                <Spotlight on={p.target === "finish"} className="w-full">
                  <button
                    onClick={p.onFinish}
                    className="flex w-full items-center justify-center gap-1.5 rounded-full border-2 border-[#18181B] bg-white py-2 text-[13px] font-bold text-[#18181B] transition hover:bg-[#FEF9C3]"
                  >
                    {awaiting ? "Approve & Call Engineer" : "Finish Triage & Call Engineer"} <ArrowRight size={15} />
                  </button>
                </Spotlight>
              )}
              {live || p.phase === "ending" ? (
                <div className="flex gap-2">
                  <button
                    onClick={p.onStop}
                    disabled={busy}
                    className="flex flex-1 items-center justify-center gap-2 rounded-full bg-rose-600 py-3.5 text-[15px] font-semibold text-white transition hover:bg-rose-500 disabled:opacity-60"
                  >
                    {busy ? <Loader2 size={18} className="animate-spin" /> : <PhoneOff size={18} />}
                    End Voice Call
                  </button>
                  <button
                    onClick={p.onToggleMic}
                    disabled={busy}
                    aria-label={p.micMuted ? "Unmute microphone" : "Mute microphone"}
                    className={`grid w-[52px] place-items-center rounded-full border-2 transition ${
                      p.micMuted ? "border-rose-300 bg-rose-50 text-rose-600" : "border-[#E4E4E7] text-[#18181B] hover:border-[#FACC15]"
                    }`}
                  >
                    {p.micMuted ? <MicOff size={18} /> : <Mic size={18} />}
                  </button>
                </div>
              ) : (
                <Spotlight on={p.target === "start"} className="w-full">
                  <button
                    onClick={p.onStart}
                    disabled={busy || p.simulated}
                    className="flex w-full items-center justify-center gap-2 rounded-full bg-[#FACC15] py-3.5 text-[15px] font-semibold text-zinc-950 shadow-sm transition hover:bg-yellow-400 disabled:opacity-60"
                  >
                    {busy ? <Loader2 size={18} className="animate-spin" /> : <PhoneCall size={18} />}
                    {busy ? "Connecting…" : p.simulated ? "Demo Sim running…" : `Start ${p.lang.short} Voice Call`}
                  </button>
                </Spotlight>
              )}
            </div>
          </div>
        )}

        {/* ---------------------------------------------------------------- Screen C: incoming call on engineer's phone */}
        {p.demoStage === "ENGINEER_RINGING" && (
          <div className="flex min-h-0 flex-1 flex-col items-center justify-between bg-gradient-to-b from-white to-[#FEFCE8] px-6 pb-6 pt-8">
            <div className="text-center">
              <p className="text-[12px] font-semibold uppercase tracking-widest text-zinc-500">Incoming call</p>
              <p className="mt-1 text-[20px] font-black text-[#18181B]">SyncUp AI Dispatch</p>
              <p className="text-[13px] font-semibold text-rose-600">
                {p.priority ?? "P1"} Incident ({p.scenario}) {p.ticketId ? `• ${p.ticketId}` : ""}
              </p>
            </div>
            <div className="relative grid h-44 w-44 place-items-center">
              {[0, 0.7, 1.4].map((d) => (
                <span key={d} className="absolute inset-6 animate-radar rounded-full border-4 border-[#FACC15]" style={{ animationDelay: `${d}s` }} />
              ))}
              <span className="absolute inset-10 animate-radar rounded-full bg-emerald-200/50" style={{ animationDelay: "0.35s" }} />
              <span className="relative grid h-24 w-24 place-items-center rounded-full bg-[#FACC15] text-[#18181B] shadow-lg">
                <PhoneCall size={38} className="animate-bounce" />
              </span>
            </div>
            <div className="w-full space-y-4">
              <div className="flex items-center justify-center gap-2 text-[12px]">
                <span className="text-zinc-500">Brief me in</span>
                {(["en-IN", "ml-IN"] as const).map((l) => (
                  <button
                    key={l}
                    onClick={() => setEngLang(l)}
                    className={`rounded-full px-2.5 py-0.5 font-semibold ${engLang === l ? "bg-[#18181B] text-[#FACC15]" : "bg-zinc-100 text-zinc-500"}`}
                  >
                    {l === "en-IN" ? "English" : "മലയാളം"}
                  </button>
                ))}
                <button onClick={() => setRingMuted((m) => !m)} aria-label={ringMuted ? "Unmute ringtone" : "Mute ringtone"} className="ml-1 text-zinc-500 hover:text-[#18181B]">
                  {ringMuted ? <BellOff size={15} /> : <BellRing size={15} className="animate-pulse" />}
                </button>
              </div>
              <div className="flex items-end justify-around">
                <div className="flex flex-col items-center gap-1.5">
                  <button
                    onClick={p.onDecline}
                    aria-label="Decline call"
                    className="grid h-16 w-16 place-items-center rounded-full bg-rose-600 text-white shadow-lg transition hover:bg-rose-500"
                  >
                    <PhoneOff size={26} />
                  </button>
                  <span className="text-[12px] font-medium text-zinc-500">Decline</span>
                </div>
                <div className="flex flex-col items-center gap-1.5">
                  <Spotlight on={p.target === "answer"}>
                    <button
                      onClick={() => p.onAnswer(engLang)}
                      disabled={p.engJoining}
                      aria-label="Answer call"
                      className="grid h-20 w-20 place-items-center rounded-full bg-emerald-500 text-white shadow-lg transition hover:bg-emerald-400 disabled:opacity-70"
                    >
                      {p.engJoining ? <Loader2 size={30} className="animate-spin" /> : <Phone size={32} />}
                    </button>
                  </Spotlight>
                  <span className="text-[12px] font-bold text-emerald-700">Answer</span>
                </div>
              </div>
            </div>
          </div>
        )}

        {/* ---------------------------------------------------------------- Screen D: live engineer briefing */}
        {engConnected && (
          <div className="flex min-h-0 flex-1 flex-col bg-white">
            <div className="flex shrink-0 flex-col items-center gap-1 border-b border-[#E4E4E7] px-4 py-3">
              <p className="text-[15px] font-black text-[#18181B]">SyncUp AI Dispatch</p>
              <p className={`text-[12.5px] font-semibold ${p.demoStage === "DISPATCH_CONFIRMED" ? "text-emerald-700" : "text-zinc-500"}`}>
                {engEnded ? "Call ended" : p.demoStage === "DISPATCH_CONFIRMED" ? `Dispatch confirmed • ${engClock}` : `Connected • ${engClock}`}
              </p>
              {/* emerald / yellow voice equalizer */}
              <div className="mt-1 flex h-8 items-end gap-1" aria-hidden>
                {Array.from({ length: 14 }).map((_, i) => (
                  <span
                    key={i}
                    className={`w-1.5 origin-bottom rounded-full ${i % 3 === 0 ? "bg-emerald-500" : "bg-[#FACC15]"} ${engEnded ? "h-1" : "h-8 animate-eq"}`}
                    style={{ animationDelay: `${(i * 83) % 700}ms` }}
                  />
                ))}
              </div>
            </div>
            <div ref={feedRef} className="min-h-0 flex-1 space-y-2.5 overflow-y-auto px-3 py-3">
              {(call?.transcripts ?? []).length === 0 && <p className="pt-6 text-center text-[13px] text-zinc-400">SyncUp is starting the briefing…</p>}
              {(call?.transcripts ?? []).map((t) =>
                t.role === "agent" ? (
                  <div key={t.id} className="flex animate-rise flex-col items-start">
                    <p className="max-w-[90%] rounded-[18px] rounded-bl-md bg-[#F4F4F5] px-3 py-2 text-[14px] leading-snug text-[#18181B]">{t.text}</p>
                    <span className="mt-0.5 pl-1 text-[10px] font-medium text-zinc-400">SyncUp Dispatch • Murf Falcon 2.1 • {call?.language ?? "en-IN"}</span>
                  </div>
                ) : (
                  <div key={t.id} className="flex animate-rise flex-col items-end">
                    <p className="max-w-[86%] rounded-[18px] rounded-br-md bg-[#FACC15] px-3 py-2 text-[14px] leading-snug text-[#18181B]">{t.text}</p>
                    <span className="mt-0.5 pr-1 text-[10px] font-medium text-zinc-400">{p.engineerName}</span>
                  </div>
                ),
              )}
            </div>
            <div className="shrink-0 space-y-2 p-3">
              {p.demoStage === "DISPATCH_CONFIRMED" ? (
                <>
                  <p className="flex items-center justify-center gap-1.5 rounded-xl bg-emerald-50 py-2 text-[13px] font-semibold text-emerald-800">
                    <CheckCircle2 size={16} /> {p.ticketId} dispatched{call?.eta_minutes ? ` • ETA ${call.eta_minutes} min` : ""}
                  </p>
                  {!engEnded && p.onCall && (
                    <button onClick={p.onHangUp} className="flex w-full items-center justify-center gap-2 rounded-full bg-rose-600 py-3 text-[14px] font-semibold text-white hover:bg-rose-500">
                      <PhoneOff size={16} /> Hang up
                    </button>
                  )}
                  {(engEnded || !p.onCall) && (
                    <Spotlight on={p.target === "done"} label="RUN AGAIN" className="w-full">
                      <button onClick={p.onRestart} className="flex w-full items-center justify-center gap-2 rounded-full bg-[#FACC15] py-3 text-[14px] font-semibold text-[#18181B] hover:bg-yellow-300">
                        <RotateCcw size={15} /> Start new demo
                      </button>
                    </Spotlight>
                  )}
                </>
              ) : (
                <div className="flex gap-2">
                  <Spotlight on={p.target === "confirm"} className="flex-1">
                    <button onClick={p.onConfirm} className="flex w-full items-center justify-center gap-2 rounded-full bg-emerald-500 py-3 text-[14px] font-bold text-white hover:bg-emerald-400">
                      <CheckCircle2 size={16} /> Confirm Dispatch
                    </button>
                  </Spotlight>
                  {p.onCall && (
                    <button onClick={p.onHangUp} aria-label="Hang up" className="grid w-12 place-items-center rounded-full bg-rose-600 text-white hover:bg-rose-500">
                      <PhoneOff size={17} />
                    </button>
                  )}
                </div>
              )}
              {p.onCall && !engEnded && (
                <p className="flex items-center justify-center gap-1 text-[11px] text-zinc-500">
                  <Mic size={11} /> Your mic is {p.engineerName}&apos;s phone — say “Yes, dispatch”
                </p>
              )}
            </div>
          </div>
        )}

        <div className="flex h-5 shrink-0 items-center justify-center bg-white" aria-hidden>
          <div className="h-1 w-28 rounded-full bg-zinc-900" />
        </div>
      </div>
    </aside>
  );
}
