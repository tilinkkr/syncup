"use client";

import { useState } from "react";
import { Loader2, Mic, PackageCheck, ShieldCheck } from "lucide-react";
import type { EnglishBrief } from "@/lib/types";

interface Props {
  ticket: EnglishBrief;
  langShort: string;
  question: string | null; // the agent's spoken confirmation question, in the worker's language
  onApprove: () => Promise<void>;
}

/** CONFIRM stage (human in the loop): nothing is created until the worker or a supervisor says yes. */
export function ApprovalCard({ ticket, langShort, question, onApprove }: Props) {
  const [busy, setBusy] = useState(false);
  const approve = async () => {
    setBusy(true);
    await onApprove();
    setBusy(false);
  };

  return (
    <section aria-live="polite" className="shrink-0 animate-rise overflow-hidden rounded-xl border-2 border-[#FACC15] bg-[#FEF9C3]/50 shadow-sm">
      <div className="flex flex-col gap-3 p-4 md:flex-row md:items-center">
        <div className="min-w-0 flex-1 space-y-1.5">
          <p className="flex items-center gap-1.5 text-[11.5px] font-bold uppercase tracking-wide text-amber-700">
            <ShieldCheck size={14} /> Human-in-the-loop approval
          </p>
          <div className="flex flex-wrap items-baseline gap-x-2.5 gap-y-1">
            <span className="font-display text-2xl font-black tracking-tight text-[#18181B]">{ticket.ticket_id}</span>
            <span className={`rounded px-2 py-0.5 text-[11px] font-bold ${ticket.priority === "P1" ? "bg-rose-600 text-white" : "bg-[#FACC15] text-[#18181B]"}`}>
              {ticket.priority}
            </span>
            <span className="truncate text-[13px] text-zinc-600">{ticket.summary}</span>
          </div>
          {ticket.spare_part_reserved && (
            <p className="flex items-center gap-1.5 text-[13px] text-zinc-700">
              <PackageCheck size={15} className="text-emerald-600" /> Reserve <b>{ticket.spare_part_reserved}</b> → {ticket.assigned_team}
            </p>
          )}
          {question && <p className="rounded-lg bg-white px-3 py-1.5 text-[14px] leading-snug text-[#18181B]">“{question}”</p>}
        </div>
        <div className="flex shrink-0 flex-col gap-2 md:w-56">
          <p className="flex items-center gap-2 text-[12px] font-semibold text-amber-800">
            <span className="relative grid h-6 w-6 place-items-center">
              <span className="absolute inset-0 animate-ping rounded-full bg-[#FACC15]/70" />
              <span className="relative grid h-6 w-6 place-items-center rounded-full bg-[#FACC15] text-[#18181B]">
                <Mic size={12} />
              </span>
            </span>
            Listening for {langShort} Confirmation...
          </p>
          <button
            onClick={approve}
            disabled={busy}
            className="flex items-center justify-center gap-2 rounded-full bg-emerald-600 px-4 py-2.5 text-[14px] font-semibold text-white transition hover:bg-emerald-500 disabled:opacity-60"
          >
            {busy && <Loader2 size={15} className="animate-spin" />}
            Approve &amp; Route Ticket
          </button>
        </div>
      </div>
    </section>
  );
}
