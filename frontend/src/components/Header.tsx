"use client";

import { AudioLines, Ear, Play, Power, RefreshCw } from "lucide-react";
import { ACOUSTICS, LANGUAGES, SCENARIOS } from "@/lib/config";
import type { Preflight, SyncUpState } from "@/lib/types";

export type StatusPill = "IDLE" | "CONNECTING" | "LIVE VOICE" | "DEMO SIM" | "AWAITING APPROVAL" | "TICKET ROUTED";

interface Props {
  state: SyncUpState | null;
  language: string;
  onLanguage: (code: string) => void;
  environment: string;
  onEnvironment: (id: string) => void;
  scenario: string;
  onScenario: (id: string) => void;
  locked: boolean;
  status: StatusPill;
  preflight: Preflight | null;
  preflightLoading: boolean;
  backendDown: boolean;
  onRefreshPreflight: () => void;
  onDemoSim: () => void;
  demoSimDisabled: boolean;
  echoGuard: boolean;
  onEchoGuard: (on: boolean) => void;
  onCleanup: () => void;
}

function Select({
  label,
  value,
  onChange,
  disabled,
  options,
}: {
  label: string;
  value: string;
  onChange: (v: string) => void;
  disabled: boolean;
  options: { id: string; label: string }[];
}) {
  return (
    <label className={`flex items-center gap-1.5 ${disabled ? "opacity-50" : ""}`} title={disabled ? "Locked while a call is active" : label}>
      <span className="sr-only">{label}</span>
      <select
        value={value}
        disabled={disabled}
        onChange={(e) => onChange(e.target.value)}
        className="h-8 rounded-lg border border-[#E4E4E7] bg-white px-2.5 text-[13px] font-medium text-[#18181B] outline-none transition hover:border-[#FACC15] focus:border-[#FACC15] disabled:cursor-not-allowed"
      >
        {options.map((o) => (
          <option key={o.id} value={o.id}>
            {o.label}
          </option>
        ))}
      </select>
    </label>
  );
}

function Dot({ label, ok, loading }: { label: string; ok: boolean | null; loading: boolean }) {
  return (
    <span className="flex items-center gap-1">
      <span
        className={`h-2 w-2 rounded-full ${loading && ok === null ? "animate-pulse bg-zinc-300" : ok ? "bg-emerald-500" : ok === null ? "bg-zinc-300" : "bg-rose-500"}`}
      />
      <span className="text-[11px] font-medium text-zinc-600">{label}</span>
    </span>
  );
}

export function Header(p: Props) {
  const pf = p.preflight;
  const down = p.backendDown ? false : null;
  const tooltip = p.backendDown ? "Backend unreachable on :8000" : pf?.hints?.length ? pf.hints.join("\n") : "All systems go — click to re-check";

  return (
    <header className="shrink-0 border-b border-[#E4E4E7] bg-white">
      <div className="flex flex-wrap items-center gap-x-5 gap-y-2 px-4 py-2.5 lg:px-6">
        <div className="flex items-center gap-2.5">
          <div className="flex h-9 items-center gap-1.5 rounded-lg bg-[#FACC15] px-2.5 text-[#18181B]">
            <AudioLines size={18} strokeWidth={2.6} />
            <span className="font-display text-[17px] font-black tracking-tight">SyncUp</span>
          </div>
          <p className="hidden text-[11.5px] leading-tight text-zinc-500 md:block">
            Voice AI at Work
            <br />
            Agora ConvoAI + Murf Falcon 2.1
          </p>
        </div>

        <div className="ml-auto flex flex-wrap items-center gap-2">
          <Select
            label="Worker language"
            value={p.language}
            onChange={p.onLanguage}
            disabled={p.locked}
            options={LANGUAGES.map((l) => ({ id: l.code, label: l.label }))}
          />
          <Select
            label="Scenario"
            value={p.scenario}
            onChange={p.onScenario}
            disabled={p.locked}
            options={SCENARIOS.map((s) => ({ id: s.id, label: `${s.label} · ${s.detail}` }))}
          />
          <Select
            label="Room acoustics"
            value={p.environment}
            onChange={p.onEnvironment}
            disabled={p.locked}
            options={ACOUSTICS.map((a) => ({ id: a.id, label: a.label }))}
          />
          <button
            role="switch"
            aria-checked={p.echoGuard}
            onClick={() => p.onEchoGuard(!p.echoGuard)}
            title={p.echoGuard ? "Mic pauses while SyncUp speaks — no echo on laptop speakers. Turn off with headphones for instant barge-in." : "Full duplex: use headphones"}
            className={`flex h-8 items-center gap-2 rounded-full border px-3 text-[12.5px] font-semibold transition ${
              p.echoGuard ? "border-[#FACC15] bg-[#FEF9C3] text-[#18181B]" : "border-[#E4E4E7] bg-white text-zinc-500"
            }`}
          >
            <Ear size={14} />
            Speaker Echo Guard
            <span className={`relative h-4 w-7 rounded-full transition ${p.echoGuard ? "bg-[#18181B]" : "bg-zinc-300"}`}>
              <span className={`absolute top-0.5 h-3 w-3 rounded-full bg-white transition-all ${p.echoGuard ? "left-3.5" : "left-0.5"}`} />
            </span>
          </button>
          <button
            onClick={p.onRefreshPreflight}
            title={tooltip}
            className="flex h-8 items-center gap-2.5 rounded-full border border-[#E4E4E7] bg-white px-3 hover:border-[#FACC15]"
          >
            <Dot label="Agora" loading={p.preflightLoading} ok={pf ? pf.agora_creds && pf.agora_rest === "OK" : down} />
            <Dot label="Murf 2.1" loading={p.preflightLoading} ok={pf ? pf.murf_api === "OK" : down} />
            <Dot label="Tunnel" loading={p.preflightLoading} ok={pf ? pf.webhook_tunnel === "OK" : down} />
            <RefreshCw size={11} className={`text-zinc-400 ${p.preflightLoading ? "animate-spin" : ""}`} />
          </button>
          <button
            onClick={p.onCleanup}
            title="Stop every Agora agent this backend started (zombie cleanup)"
            aria-label="Stop all agents"
            className="grid h-8 w-8 place-items-center rounded-full border border-[#E4E4E7] bg-white text-zinc-500 transition hover:border-rose-300 hover:text-rose-600"
          >
            <Power size={14} />
          </button>
          <button
            onClick={p.onDemoSim}
            disabled={p.demoSimDisabled}
            title="Scripted Malayalam run through the real engine — use it if venue Wi-Fi blocks the live call"
            className="flex h-8 items-center gap-1.5 rounded-full bg-[#18181B] px-4 text-[13px] font-bold text-[#FACC15] transition hover:bg-zinc-700 disabled:cursor-not-allowed disabled:opacity-40"
          >
            <Play size={12} fill="currentColor" /> Demo Sim
          </button>
        </div>
      </div>
    </header>
  );
}
