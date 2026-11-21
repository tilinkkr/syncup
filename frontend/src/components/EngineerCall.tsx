"use client";

import { useEffect, useRef, useState } from "react";
import { CheckCircle2, Mic, PhoneCall, PhoneOff, PhoneOutgoing } from "lucide-react";
import type { Escalation } from "@/lib/types";

interface Props {
  call: Escalation;
  workerLang: string;
  live: boolean; // a real Agora call (vs Demo Sim)
  onCall: boolean; // the browser is joined as the engineer's handset
  getLevel: () => number;
  onHangUp: () => void;
}

const fmt = (s: number) => `${String(Math.floor(s / 60)).padStart(2, "0")}:${String(Math.floor(s % 60)).padStart(2, "0")}`;

/** AFTER stage: SyncUp phones the on-call engineer and briefs them in English. Looks and behaves like a call. */
export function EngineerCall({ call, workerLang, live, onCall, getLevel, onHangUp }: Props) {
  const [now, setNow] = useState(Date.now() / 1000);
  const ringRef = useRef<HTMLSpanElement>(null);
  const feedRef = useRef<HTMLDivElement>(null);
  const eng = call.engineer;
  const initials = eng.name.split(" ").map((w) => w[0]).join("").slice(0, 2);
  const ringing = call.status === "dialing" || call.status === "ringing";
  const ended = call.status === "completed" || call.status === "failed";
  const acked = call.accepted !== null && call.accepted !== undefined;

  useEffect(() => {
    const id = setInterval(() => setNow(Date.now() / 1000), 1000);
    return () => clearInterval(id);
  }, []);

  // Voice-reactive ring around the avatar (live calls); CSS pulse covers the Demo Sim.
  useEffect(() => {
    if (!live) return;
    let raf = 0;
    const tick = () => {
      const v = Math.min(1, getLevel() * 2.2);
      if (ringRef.current) ringRef.current.style.transform = `scale(${1 + v * 0.35})`;
      raf = requestAnimationFrame(tick);
    };
    raf = requestAnimationFrame(tick);
    return () => cancelAnimationFrame(raf);
  }, [live, getLevel]);

  useEffect(() => {
    feedRef.current?.scrollTo({ top: feedRef.current.scrollHeight, behavior: "smooth" });
  }, [call.transcripts.length]);

  const status = call.status === "dialing"
    ? "Dialing…"
    : call.status === "ringing"
      ? "Ringing…"
      : call.status === "failed"
        ? "Call failed"
        : ended
          ? `Call ended${call.connected_at && call.ended_at ? ` · ${fmt(call.ended_at - call.connected_at)}` : ""}`
          : `Connected · ${call.connected_at ? fmt(now - call.connected_at) : "00:00"}`;

  return (
    <section aria-live="polite" className="flex min-h-[16rem] flex-1 animate-rise flex-col overflow-hidden rounded-xl border-2 border-[#FACC15] bg-white shadow-[0_8px_30px_-12px_rgba(234,179,8,0.6)] lg:min-h-0">
      <header className="flex flex-wrap items-center gap-2 border-b border-yellow-100 bg-yellow-50 px-5 py-2.5">
        <PhoneOutgoing size={16} className="text-yellow-700" />
        <h3 className="text-[14px] font-bold text-zinc-800">Outbound call to engineering</h3>
        <span className="rounded-full bg-white px-2 py-0.5 text-xs font-semibold text-zinc-600">English · Murf voice</span>
        <span className="ml-auto text-xs text-zinc-500">Ticket {call.ticket_id}</span>
      </header>

      <div className="flex min-h-0 flex-1 flex-col md:flex-row">
        {/* Phone */}
        <div className="flex shrink-0 flex-col items-center justify-center gap-3 border-zinc-100 px-5 py-4 md:w-56 md:border-r">
          <div className="relative grid h-16 w-16 place-items-center">
            {!ended && (
              <>
                <span ref={ringRef} className={`absolute inset-0 rounded-full bg-yellow-200 transition-transform duration-75 ${ringing ? "animate-ping" : ""}`} />
                {ringing && <span className="absolute -inset-3 animate-pulse rounded-full border-2 border-yellow-300" />}
              </>
            )}
            <span className={`relative grid h-16 w-16 place-items-center rounded-full text-2xl font-black ${ended ? "bg-zinc-100 text-zinc-400" : "bg-yellow-400 text-zinc-900"}`}>
              {initials}
            </span>
          </div>
          <div className="text-center leading-tight">
            <p className="text-[17px] font-bold text-zinc-800">{eng.name}</p>
            <p className="text-[13px] text-zinc-500">{eng.role}</p>
          </div>
          <p className={`flex items-center gap-1.5 text-[14px] font-semibold ${call.status === "failed" ? "text-rose-600" : ended ? "text-zinc-500" : ringing ? "text-yellow-700" : "text-emerald-600"}`}>
            {ringing ? <PhoneCall size={15} className="animate-bounce" /> : !ended && <span className="h-2 w-2 animate-pulse rounded-full bg-emerald-500" />}
            {status}
          </p>
          {live && !ended && (
            <button onClick={onHangUp} className="flex items-center gap-2 rounded-full bg-rose-600 px-5 py-2 text-[14px] font-bold text-white transition hover:bg-rose-500">
              <PhoneOff size={16} /> Hang up
            </button>
          )}
          {live && onCall && !ended && (
            <p className="flex items-center gap-1.5 text-center text-xs text-zinc-500">
              <Mic size={12} /> Your mic is the engineer&apos;s phone — answer him
            </p>
          )}
        </div>

        {/* Live English captions */}
        <div className="flex min-h-0 flex-1 flex-col">
          <div ref={feedRef} className="min-h-[8rem] flex-1 space-y-3 overflow-y-auto px-5 py-4">
            {call.transcripts.length === 0 && (
              <p className="pt-6 text-center text-sm text-zinc-400">{ringing ? `Calling ${eng.first}…` : "Waiting for the line…"}</p>
            )}
            {call.transcripts.map((t) =>
              t.role === "agent" ? (
                <div key={t.id} className="flex animate-rise flex-col items-start">
                  <span className="mb-1 text-[11px] font-medium text-zinc-400">SyncUp (AI) → {eng.first}</span>
                  <p className="max-w-[90%] rounded-2xl rounded-bl-md border border-zinc-200 bg-white px-3.5 py-2 text-[15px] leading-snug text-zinc-800 shadow-sm">{t.text}</p>
                </div>
              ) : (
                <div key={t.id} className="flex animate-rise flex-col items-end">
                  <span className="mb-1 text-[11px] font-medium text-zinc-400">{eng.name}</span>
                  <p className="max-w-[85%] rounded-2xl rounded-br-md bg-yellow-400 px-3.5 py-2 text-[15px] leading-snug text-zinc-900">{t.text}</p>
                </div>
              ),
            )}
          </div>
          {acked && (
            <div className={`flex shrink-0 items-center gap-2 border-t px-5 py-2.5 text-[14px] ${call.accepted ? "border-emerald-200 bg-emerald-50 text-emerald-800" : "border-rose-200 bg-rose-50 text-rose-700"}`}>
              <CheckCircle2 size={17} className={call.accepted ? "text-emerald-600" : "text-rose-600"} />
              {call.accepted ? (
                <span>
                  <b>{eng.first} is coming</b>
                  {call.eta_minutes ? ` · arriving in ${call.eta_minutes} min` : ""} · worker updated in {workerLang}
                </span>
              ) : (
                <span>
                  <b>{eng.first} can&apos;t attend</b> · escalate to shift supervisor
                </span>
              )}
            </div>
          )}
        </div>
      </div>
    </section>
  );
}
