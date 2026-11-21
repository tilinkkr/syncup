"use client";

import { Check, Database, QrCode, ScanLine } from "lucide-react";
import type { AssetContext } from "@/lib/types";

const ASSET_LABEL: Record<string, string> = {
  "LINE-03": "Bosch Pack-400",
  "GATE-02": "Dispatch Scanner",
};

interface Props {
  scenario: string;
  context: AssetContext | null;
  onScan: () => void;
  compact?: boolean; // once the call is running, shrink to one line
}

/** BEFORE stage, on the worker's phone: scanning the machine's QR sticker loads its maintenance history. */
export function QrAssetCard({ scenario, context, onScan, compact = false }: Props) {
  const loaded = context && context.asset_id === scenario ? context : null;
  const scanned = !!loaded;
  const log = loaded?.maintenance_logs[0];
  const sop = loaded?.sops[0];

  return (
    <section className="shrink-0 rounded-2xl border border-[#E4E4E7] bg-white p-3 shadow-sm">
      <div className="flex items-center gap-2.5">
        <div className={`grid h-9 w-9 shrink-0 place-items-center rounded-xl ${scanned ? "bg-[#18181B] text-[#FACC15]" : "bg-[#FEF9C3] text-amber-600"}`}>
          {scanned ? <Check size={18} strokeWidth={3} /> : <QrCode size={18} />}
        </div>
        <div className="min-w-0 flex-1 leading-tight">
          <p className="truncate text-[14px] font-bold text-[#18181B]">
            {ASSET_LABEL[scenario] ?? scenario} <span className="font-medium text-zinc-400">• {scenario}</span>
          </p>
          <p className="truncate text-[11.5px] text-zinc-500">{scanned ? "History loaded from QR" : "Scan before you call"}</p>
        </div>
        {!scanned && (
          <button
            onClick={onScan}
            className="flex shrink-0 items-center gap-1 rounded-full bg-[#FACC15] px-3 py-1.5 text-[12px] font-semibold text-[#18181B] transition hover:bg-yellow-300"
          >
            <ScanLine size={13} /> Scan Machine QR
          </button>
        )}
      </div>
      {loaded && !compact && (
        <div className="mt-2.5 animate-rise space-y-1.5 border-t border-zinc-100 pt-2.5">
          {log && (
            <p className="flex items-start gap-2 text-[12px] leading-snug text-zinc-700">
              <span className="flex shrink-0 items-center gap-1 rounded-md bg-emerald-50 px-1.5 py-0.5 font-mono text-[10.5px] font-semibold text-emerald-700">
                <Database size={10} /> {log.log_id}
              </span>
              <span>
                {log.component}: <b className="text-emerald-700">{log.status}</b> <span className="text-zinc-400">({log.date})</span>
              </span>
            </p>
          )}
          {sop && (
            <p className="flex items-start gap-2 text-[12px] leading-snug text-zinc-600">
              <span className="shrink-0 rounded-md bg-[#FEF9C3] px-1.5 py-0.5 font-mono text-[10.5px] font-semibold text-amber-700">SOP {sop.code}</span>
              <span>{sop.fault}</span>
            </p>
          )}
        </div>
      )}
    </section>
  );
}
