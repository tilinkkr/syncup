"use client";

import { useState } from "react";
import { CalendarClock, Check, ClipboardCopy, FileText, Loader2, PhoneOutgoing, Send } from "lucide-react";
import type { EnglishBrief, Escalation, SessionStatus } from "@/lib/types";

export function briefToText(b: EnglishBrief): string {
  const list = (xs: string[]) => (xs.length ? xs.map((x) => `  - ${x}`).join("\n") : "  - none");
  return [
    `WORK ORDER ${b.ticket_id} [${b.priority}]`,
    `Asset: ${b.asset}`,
    `Summary: ${b.summary}`,
    `Verified facts:\n${list(b.verified_facts)}`,
    `Debunked worker assumptions:\n${list(b.debunked_claims)}`,
    `Still unverified:\n${list(b.unverified_guesses)}`,
    `Recommended action: ${b.recommended_action}`,
    `Spare part reserved: ${b.spare_part_reserved ?? "none"}`,
    `Assigned team: ${b.assigned_team}`,
    ...(b.follow_up ? [`Follow-up: ${b.follow_up}`] : []),
  ].join("\n");
}

function Field({ label, children }: { label: string; children: React.ReactNode }) {
  return (
    <div className="min-w-0">
      <p className="mb-0.5 text-[10.5px] font-bold uppercase tracking-wide text-zinc-400">{label}</p>
      <div className="text-[13px] leading-snug text-[#18181B]">{children}</div>
    </div>
  );
}

interface Props {
  brief: EnglishBrief | null;
  status: SessionStatus | undefined;
  langShort: string;
  escalation?: Escalation | null;
  canCall?: boolean;
  calling?: boolean;
  onCallEngineer?: () => void;
}

export function EngineeringBrief({ brief, status, langShort, escalation = null, canCall = false, calling = false, onCallEngineer }: Props) {
  const [copied, setCopied] = useState(false);
  const routed = status === "ROUTED" && brief;

  const copy = async () => {
    if (!brief) return;
    await navigator.clipboard.writeText(briefToText(brief)).catch(() => undefined);
    setCopied(true);
    setTimeout(() => setCopied(false), 2000);
  };

  return (
    <section className="flex min-h-[14rem] flex-col overflow-hidden rounded-xl border border-[#E4E4E7] bg-white shadow-sm lg:min-h-0">
      <header className="flex shrink-0 flex-wrap items-center gap-2 bg-[#FACC15] px-4 py-2">
        <FileText size={15} className="text-[#18181B]" />
        <h3 className="text-[13.5px] font-black uppercase tracking-wide text-[#18181B]">English Engineering Brief</h3>
        {routed && (
          <>
            <span className="flex items-center gap-1 rounded-full bg-[#18181B] px-2.5 py-0.5 text-[10.5px] font-bold text-[#FACC15]">
              <Send size={10} /> Routed{brief.approved_via ? ` · ${brief.approved_via === "voice" ? "worker approved" : "supervisor approved"}` : ""}
            </span>
            <div className="ml-auto flex items-center gap-1.5">
              {(canCall || calling) && onCallEngineer && (
                <button
                  onClick={onCallEngineer}
                  disabled={calling}
                  className="flex items-center gap-1 rounded-full bg-[#18181B] px-3 py-1 text-[11.5px] font-bold text-white transition hover:bg-zinc-700 disabled:opacity-60"
                >
                  {calling ? <Loader2 size={12} className="animate-spin" /> : <PhoneOutgoing size={12} />}
                  {calling ? "Calling…" : "Call engineer"}
                </button>
              )}
              <button
                onClick={copy}
                className={`flex items-center gap-1 rounded-full border px-3 py-1 text-[11.5px] font-bold transition ${
                  copied ? "border-emerald-600 bg-emerald-600 text-white" : "border-[#18181B]/20 bg-white text-[#18181B] hover:bg-yellow-50"
                }`}
              >
                {copied ? <Check size={12} /> : <ClipboardCopy size={12} />}
                {copied ? "Copied!" : "Copy"}
              </button>
            </div>
          </>
        )}
      </header>

      {!routed ? (
        <div className="grid flex-1 place-items-center p-5 text-center">
          <div>
            <p className="text-[15px] font-bold text-zinc-400">{status === "INVESTIGATING" ? "Investigation in progress…" : "No work order yet"}</p>
            <p className="mx-auto mt-0.5 max-w-sm text-[12.5px] text-zinc-400">
              The {langShort} conversation is compiled here into a clean English ticket for the maintenance team.
            </p>
          </div>
        </div>
      ) : (
        <>
          <div className="min-h-0 flex-1 overflow-y-auto px-4 py-3">
            <div className="mb-2.5 flex flex-wrap items-baseline gap-x-3 gap-y-1">
              <span className="text-[10.5px] font-bold uppercase tracking-wide text-zinc-400">Ticket ID</span>
              <span className="font-display text-2xl font-black tracking-tight text-[#18181B]">{brief.ticket_id}</span>
              <span className={`rounded px-2 py-0.5 text-[11px] font-bold ${brief.priority === "P1" ? "bg-rose-600 text-white" : "bg-[#FEF9C3] text-[#18181B]"}`}>
                Priority {brief.priority}
              </span>
              <span className="min-w-0 truncate text-[12.5px] text-zinc-600">{brief.asset}</span>
            </div>
            <div className="grid grid-cols-1 gap-x-5 gap-y-2.5 sm:grid-cols-2">
              <Field label="Verified facts">
                <ul className="space-y-0.5">
                  {brief.verified_facts.map((f) => (
                    <li key={f} className="flex gap-1">
                      <Check size={13} className="mt-0.5 shrink-0 text-emerald-600" /> {f}
                    </li>
                  ))}
                </ul>
              </Field>
              <Field label="Debunked assumptions">
                <ul className="space-y-0.5">
                  {brief.debunked_claims.length ? (
                    brief.debunked_claims.map((d) => (
                      <li key={d} className="text-rose-700">
                        ✕ {d.replace(/ \(disproved by .*$/, "")}
                      </li>
                    ))
                  ) : (
                    <li className="text-zinc-400">None</li>
                  )}
                </ul>
              </Field>
              <Field label="Action & spare part">
                {brief.recommended_action}
                {brief.spare_part_reserved && <span className="mt-0.5 block font-semibold text-emerald-700">Reserved: {brief.spare_part_reserved}</span>}
              </Field>
              <Field label="Assigned team">
                <span className="font-semibold">{brief.assigned_team}</span>
                {escalation && (
                  <span className="mt-0.5 flex items-center gap-1 text-[12.5px] text-zinc-600">
                    <PhoneOutgoing size={12} className={escalation.accepted === false ? "text-rose-600" : "text-emerald-600"} />
                    {escalation.engineer.name}
                    {escalation.accepted === true
                      ? ` · coming${escalation.eta_minutes ? ` in ${escalation.eta_minutes} min` : ""}`
                      : escalation.accepted === false
                        ? " · declined"
                        : ` · ${escalation.status}`}
                  </span>
                )}
              </Field>
            </div>
          </div>
          <footer className="flex shrink-0 items-center gap-2 border-t border-yellow-200 bg-[#FEFCE8] px-4 py-2">
            <span className="rounded-full bg-[#18181B] px-2 py-0.5 text-[10px] font-bold uppercase tracking-wide text-[#FACC15]">After</span>
            <CalendarClock size={14} className="text-amber-700" />
            <span className="truncate text-[12.5px] font-semibold text-[#18181B]">30-min Automated {langShort} Follow-Up Scheduled</span>
            <span className="ml-auto hidden shrink-0 text-[11px] text-zinc-500 sm:inline">
              Ops webhook: {brief.ops_webhook === "dispatched" ? "dispatched" : "logged locally"}
            </span>
          </footer>
        </>
      )}
    </section>
  );
}
