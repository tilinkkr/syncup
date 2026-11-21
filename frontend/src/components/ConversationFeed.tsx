"use client";

import { useEffect, useRef } from "react";
import type { LanguageOption } from "@/lib/config";
import type { Transcript } from "@/lib/types";

/** Chat bubbles inside the phone: worker = signal yellow, SyncUp = light grey with the Murf voice tag. */
export function ConversationFeed({ transcripts, lang }: { transcripts: Transcript[]; lang: LanguageOption }) {
  const ref = useRef<HTMLDivElement>(null);
  const last = transcripts[transcripts.length - 1];

  useEffect(() => {
    const el = ref.current;
    if (el) el.scrollTo({ top: el.scrollHeight, behavior: "smooth" });
  }, [transcripts.length, last?.text]);

  return (
    <div ref={ref} className="min-h-0 flex-1 space-y-2.5 overflow-y-auto px-3 py-3" aria-label={`Live ${lang.short} conversation`}>
      {transcripts.length === 0 && (
        <p className="px-4 pt-6 text-center text-[13px] leading-relaxed text-zinc-400">
          Tap <span className="font-semibold text-zinc-600">Start {lang.short} Voice Call</span> and talk to SyncUp. Captions appear here live.
        </p>
      )}
      {transcripts.map((t) =>
        t.role === "worker" ? (
          <div key={t.id} className="flex animate-rise flex-col items-end">
            <p
              className={`max-w-[86%] rounded-[18px] rounded-br-md bg-[#FACC15] px-3 py-2 text-[14px] leading-snug text-[#18181B] ${
                t.isFinal ? "" : "opacity-70"
              }`}
            >
              {t.text}
              {!t.isFinal && <span className="ml-1 inline-block animate-pulse">▍</span>}
            </p>
          </div>
        ) : (
          <div key={t.id} className="flex animate-rise flex-col items-start">
            <p
              className={`max-w-[88%] rounded-[18px] rounded-bl-md bg-[#F4F4F5] px-3 py-2 text-[14px] leading-snug text-[#18181B] ${
                t.interrupted ? "opacity-60" : ""
              }`}
            >
              {t.text}
              {!t.isFinal && <span className="ml-1 inline-block animate-pulse text-amber-500">▍</span>}
            </p>
            <span className="mt-0.5 flex items-center gap-1 pl-1 text-[10px] font-medium text-zinc-400">
              Murf Falcon 2.1 • {lang.code}
              {t.interrupted && <span className="font-semibold text-rose-500">· interrupted</span>}
            </span>
          </div>
        ),
      )}
    </div>
  );
}
