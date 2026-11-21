"use client";

import { CheckCircle2, CircleHelp, Database, ScanSearch } from "lucide-react";
import type { ReactNode } from "react";
import type { LanguageOption } from "@/lib/config";
import type { SyncUpState } from "@/lib/types";

function Card({ title, count, bar, icon, hint, children }: { title: string; count: number; bar: string; icon: ReactNode; hint: string; children: ReactNode }) {
  return (
    <section className="flex min-h-[11rem] flex-col overflow-hidden rounded-xl border border-[#E4E4E7] bg-white shadow-sm lg:min-h-0">
      <div className={`h-1.5 shrink-0 ${bar}`} />
      <header className="flex items-center gap-2 px-3.5 pb-1.5 pt-2.5">
        {icon}
        <h3 className="text-[14px] font-bold text-[#18181B]">{title}</h3>
        <span className="ml-auto rounded-full bg-zinc-100 px-2 text-[11px] font-semibold tabular-nums text-zinc-500">{count}</span>
      </header>
      <div className="flex-1 space-y-2 overflow-y-auto px-3.5 pb-3">
        {count === 0 && <p className="text-[12.5px] leading-relaxed text-zinc-400">{hint}</p>}
        {children}
      </div>
    </section>
  );
}

export function TriageBoard({ state, lang }: { state: SyncUpState | null; lang: LanguageOption }) {
  const facts = state?.verified_facts ?? [];
  const guesses = state?.unverified_guesses ?? [];
  const debunked = state?.debunked_claims ?? [];
  const unknowns = state?.missing_unknowns ?? [];
  const check = state?.active_check;

  return (
    <div className="grid min-h-0 grid-cols-1 gap-3 md:grid-cols-3">
      <Card
        title="Verified Facts"
        hint="Confirmed observations: error codes, lights, machine state."
        count={facts.length}
        bar="bg-emerald-500"
        icon={<CheckCircle2 size={16} className="text-emerald-600" />}
      >
        {facts.map((f) => (
          <p key={f.text} className="animate-rise rounded-lg border-l-[3px] border-emerald-500 bg-emerald-50/60 px-2.5 py-1.5 text-[13.5px] text-[#18181B]">
            {f.text}
          </p>
        ))}
      </Card>

      <Card
        title="Worker Guesses → Fact Check"
        hint="Assumptions are checked against the maintenance logs."
        count={guesses.length + debunked.length}
        bar={debunked.length ? "bg-rose-600" : "bg-[#FACC15]"}
        icon={<ScanSearch size={16} className={debunked.length ? "text-rose-600" : "text-amber-500"} />}
      >
        {debunked.map((d) => (
          <div key={d.text} className="animate-rise animate-flash rounded-lg border border-rose-200 bg-rose-50/60 px-2.5 py-2">
            <span className="mb-1 inline-flex items-center gap-1 rounded bg-rose-600 px-1.5 py-0.5 text-[10px] font-bold uppercase tracking-wide text-white">
              <Database size={10} /> Debunked by {d.log_id}
            </span>
            <p className="text-[13.5px] text-zinc-500 line-through decoration-rose-500 decoration-2">{d.text}</p>
            <p className="mt-0.5 text-[12px] font-medium text-rose-700">{d.evidence.split(": ").slice(1).join(": ")}</p>
          </div>
        ))}
        {guesses.map((g) => (
          <div key={g.text} className="animate-rise rounded-lg border-l-[3px] border-[#FACC15] bg-[#FEFCE8] px-2.5 py-1.5">
            <p className="text-[13.5px] text-[#18181B]">{g.text}</p>
            <p className="text-[11px] font-semibold text-amber-700">Unverified — needs a physical check</p>
          </div>
        ))}
      </Card>

      <Card
        title="Missing Unknowns"
        hint="What SyncUp still needs before raising a ticket."
        count={unknowns.length}
        bar="bg-[#18181B]"
        icon={<CircleHelp size={16} className="text-[#18181B]" />}
      >
        {check?.question && (
          <div className="animate-rise rounded-lg border border-amber-300 bg-[#FEF9C3] px-2.5 py-2">
            <p className="text-[11px] font-semibold text-amber-800">SyncUp is asking in {lang.short}</p>
            <p className="text-[13.5px] font-medium text-[#18181B]">Is {check.question}?</p>
          </div>
        )}
        {unknowns
          .filter((u) => u.resolved || !check?.question)
          .map((u) =>
            u.resolved ? (
              <p key={u.text} className="flex items-start gap-1.5 rounded-lg bg-zinc-50 px-2.5 py-1.5 text-[13px] text-zinc-400">
                <CheckCircle2 size={14} className="mt-0.5 shrink-0 text-emerald-600" />
                <span className="line-through">{u.text}</span>
                <span className="ml-auto shrink-0 text-[10px] font-semibold uppercase text-emerald-600">answered</span>
              </p>
            ) : (
              <p key={u.text} className="animate-rise rounded-lg bg-zinc-50 px-2.5 py-1.5 text-[13px] text-zinc-700">
                {u.text}
              </p>
            ),
          )}
      </Card>
    </div>
  );
}
