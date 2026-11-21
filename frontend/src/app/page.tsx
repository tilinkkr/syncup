"use client";

import { useEffect, useState } from "react";
import { EngineeringBrief } from "@/components/EngineeringBrief";
import { Header, type StatusPill } from "@/components/Header";
import { JourneyRail } from "@/components/JourneyRail";
import { LiveLogBox } from "@/components/LiveLogBox";
import { TriageBoard } from "@/components/TriageBoard";
import { WorkerPane, type GuideTarget } from "@/components/WorkerPane";
import { useAgoraSession } from "@/hooks/useAgoraSession";
import { usePreflight } from "@/hooks/usePreflight";
import { BACKEND_URL, languageByCode, SCENARIOS } from "@/lib/config";

export default function CommandCenter() {
  const [language, setLanguage] = useState("ml-IN");
  const [environment, setEnvironment] = useState("stage_noisy");
  const [scenario, setScenario] = useState(SCENARIOS[0].id);
  const session = useAgoraSession();
  const preflight = usePreflight();
  const { state, phase, engPhase, hangUpEngineer } = session;
  const locked = phase !== "idle";
  const simulated = !!state?.simulated;
  const lang = languageByCode((locked || simulated) && state?.language ? state.language : language);
  const status = state?.status;
  const stage = state?.demo_stage ?? "QR_READY";
  const esc = state?.escalation ?? null;
  const brief = state?.english_brief ?? null;
  const engineer = esc?.engineer ?? state?.engineer_brief?.engineer ?? null;
  const machine = state?.asset_hint ?? scenario;

  // After the engineer confirms on a live call, let SyncUp say goodbye, then hang up (one voice at a time).
  useEffect(() => {
    if (stage !== "DISPATCH_CONFIRMED" || engPhase !== "on_call") return;
    const t = setTimeout(() => void hangUpEngineer(), 9000);
    return () => clearTimeout(t);
  }, [stage, engPhase, hangUpEngineer]);

  // Judge click guide: exactly one target is spotlighted at every step.
  const triaged = (state?.verified_facts.length ?? 0) > 0 || status === "AWAITING_APPROVAL";
  let target: GuideTarget = "qr";
  let guide = "";
  switch (stage) {
    case "QR_READY":
      target = "qr";
      guide = `Step 1: Click the QR code inside the phone to scan Machine ${machine.replace("-", " ")}`;
      break;
    case "WORKER_CALL":
      if (simulated) {
        target = "listen";
        guide = "Step 2: Demo Sim is talking to Ramesh in Malayalam — watch facts vs. guesses fill in";
      } else if (phase !== "live") {
        target = "start";
        guide = "Step 2: Tap 'Start Malayalam Voice Call' on the phone, then describe the fault in Malayalam";
      } else if (triaged) {
        target = "finish";
        guide = "Step 2: Speak Malayalam or click 'Finish Triage & Call Engineer' to trigger the engineer call";
      } else {
        target = "listen";
        guide = "Step 2: Speak Malayalam — tell SyncUp what's wrong with the machine";
      }
      break;
    case "ENGINEER_RINGING":
      target = "answer";
      guide = "Step 3: Click the pulsing green button to answer SyncUp's outbound call";
      break;
    case "ENGINEER_CONNECTED":
      target = "confirm";
      guide = "Step 4: Listen to the briefing, then say “Yes, dispatch” or tap Confirm Dispatch";
      break;
    case "DISPATCH_CONFIRMED":
      target = "done";
      guide = `Dispatch verified • ${brief?.ticket_id ?? ""} routed • ${engineer?.first ?? "Engineer"} on the way`;
      break;
  }

  const pill: StatusPill = status === "ROUTED" ? "TICKET ROUTED" : phase === "live" ? "LIVE VOICE" : simulated ? "DEMO SIM" : "IDLE";
  const simRunning = simulated && stage !== "DISPATCH_CONFIRMED";

  const cleanup = async () => {
    await fetch(`${BACKEND_URL}/api/session/cleanup`, { method: "POST" }).catch(() => undefined);
    await session.resetDemo();
  };

  return (
    <main className="flex h-screen flex-col overflow-y-auto bg-[#FAFAF9] text-[#18181B] lg:overflow-hidden">
      <Header
        state={state}
        language={language}
        onLanguage={setLanguage}
        environment={environment}
        onEnvironment={setEnvironment}
        scenario={scenario}
        onScenario={setScenario}
        locked={locked}
        status={pill}
        preflight={preflight.data}
        preflightLoading={preflight.loading}
        backendDown={preflight.backendDown}
        onRefreshPreflight={preflight.refresh}
        onDemoSim={() => {
          setLanguage("ml-IN");
          setScenario("LINE-03");
          session.simulate();
        }}
        demoSimDisabled={locked || simRunning || engPhase !== "idle"}
        echoGuard={session.echoGuard}
        onEchoGuard={session.setEchoGuard}
        onCleanup={() => void cleanup()}
      />
      <JourneyRail stage={stage} guide={guide} />
      <div className="flex flex-1 flex-col lg:min-h-0 lg:flex-row">
        <WorkerPane
          lang={lang}
          scenario={machine}
          phase={phase}
          micMuted={session.micMuted}
          error={session.error}
          simulated={simulated}
          agentState={session.agentState}
          transcripts={session.transcripts}
          latency={session.latency}
          getLevels={session.getLevels}
          assetContext={state?.asset_context ?? null}
          guardMuting={session.guardMuting}
          demoStage={stage}
          status={status}
          target={target}
          escalation={esc}
          engineerName={engineer?.name ?? "Arjun M."}
          engineerRole={engineer?.role ?? "Lead Engineer"}
          ticketId={brief?.ticket_id ?? state?.engineer_brief?.ticket_id ?? null}
          priority={brief?.priority ?? null}
          engJoining={engPhase === "joining"}
          onCall={engPhase === "on_call"}
          getEngineerLevel={session.getEngineerLevel}
          onScanQr={() => session.scanQr(scenario)}
          onStart={() => session.start(language, scenario, environment)}
          onStop={session.stop}
          onToggleMic={session.toggleMic}
          onFinish={() => void session.ringEngineer()}
          onAnswer={(l) => void session.answerEngineer(l)}
          onDecline={() => void session.declineEngineer()}
          onConfirm={() => void session.confirmDispatch()}
          onHangUp={() => void hangUpEngineer()}
          onRestart={() => void session.resetDemo()}
        />
        <section className="flex min-h-0 flex-1 flex-col gap-3 p-3 lg:w-[60%] lg:p-5">
          <div className="flex flex-wrap items-baseline gap-x-3 gap-y-0.5">
            <h2 className="font-display text-[22px] font-black tracking-tight text-[#18181B]">Live Epistemic Triage</h2>
            <p className="text-[12.5px] text-zinc-500">
              Worker claims checked against {state?.asset_id ?? machine} maintenance records • ground truth: company_context.json
            </p>
          </div>
          <div className="lg:h-[46%] lg:min-h-0 lg:shrink-0 [&>div]:h-full">
            <TriageBoard state={state} lang={lang} />
          </div>
          <div className="grid min-h-0 flex-1 grid-cols-1 gap-3 lg:grid-cols-[3fr_2fr]">
            <EngineeringBrief brief={brief} status={status} langShort={lang.short} escalation={esc} />
            <LiveLogBox logs={session.logs} />
          </div>
        </section>
      </div>
    </main>
  );
}
