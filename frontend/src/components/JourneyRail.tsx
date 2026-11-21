"use client";

import { Check, MousePointerClick } from "lucide-react";
import type { DemoStage } from "@/lib/types";

const STEPS = [
  { n: 1, title: "Click QR" },
  { n: 2, title: "Worker Triage (ml-IN)" },
  { n: 3, title: "Answer Engineer Call" },
  { n: 4, title: "Dispatch Verified" },
] as const;

const STEP_OF: Record<DemoStage, number> = {
  QR_READY: 1,
  WORKER_CALL: 2,
  ENGINEER_RINGING: 3,
  ENGINEER_CONNECTED: 3,
  DISPATCH_CONFIRMED: 5, // all done
};

/** 4-step interactive demo roadmap + the floating "what to click next" guide for judges. */
export function JourneyRail({ stage, guide }: { stage: DemoStage; guide: string }) {
  const cur = STEP_OF[stage] ?? 1;
  const done = stage === "DISPATCH_CONFIRMED";
  return (
    <div className="flex shrink-0 flex-wrap items-center gap-x-5 gap-y-2 border-b border-[#E4E4E7] bg-white px-4 py-2 lg:px-6">
      <ol className="flex min-w-0 flex-1 items-center" aria-label="Demo roadmap">
        {STEPS.map((s, i) => {
          const isDone = s.n < cur;
          const active = s.n === cur;
          return (
            <li key={s.n} className={`flex min-w-0 items-center ${i < STEPS.length - 1 ? "flex-1" : ""}`} aria-current={active ? "step" : undefined}>
              <span
                className={`flex min-w-0 items-center gap-2 rounded-full py-1 pl-1 pr-3 transition-colors duration-500 ${active ? "bg-[#FACC15] shadow-sm" : ""}`}
              >
                <span
                  className={`grid h-6 w-6 shrink-0 place-items-center rounded-full text-[12px] font-bold ${
                    isDone ? "bg-[#18181B] text-[#FACC15]" : active ? "bg-white text-[#18181B]" : "bg-zinc-100 text-zinc-400"
                  }`}
                >
                  {isDone ? <Check size={13} strokeWidth={3} /> : s.n}
                </span>
                <span className={`truncate text-[13px] font-bold ${isDone || active ? "text-[#18181B]" : "text-zinc-400"}`}>
                  {s.n}. {s.title}
                </span>
              </span>
              {i < STEPS.length - 1 && <span className={`mx-2 h-[2px] min-w-3 flex-1 rounded-full ${isDone ? "bg-[#18181B]" : "bg-zinc-200"}`} />}
            </li>
          );
        })}
      </ol>
      <p
        role="status"
        className={`flex max-w-full items-center gap-2 rounded-full border px-3.5 py-1.5 text-[13px] font-semibold shadow-sm ${
          done ? "border-emerald-300 bg-emerald-50 text-emerald-800" : "border-[#FACC15] bg-[#FEF9C3] text-[#18181B]"
        }`}
      >
        {done ? <Check size={15} className="shrink-0" /> : <MousePointerClick size={15} className="shrink-0 animate-pulse" />}
        <span className="truncate">{guide}</span>
      </p>
    </div>
  );
}
