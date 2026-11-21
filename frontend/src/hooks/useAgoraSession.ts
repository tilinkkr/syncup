"use client";

import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import type { IAgoraRTCClient, IAgoraRTCRemoteUser, IMicrophoneAudioTrack, IRemoteAudioTrack } from "agora-rtc-sdk-ng";
import { ChunkAssembler, decodePayload, parseAgentMessage, type AgentEvent } from "@/lib/agentMessages";
import { BACKEND_URL, CHANNEL_NAME } from "@/lib/config";
import type {
  AgentState,
  CallPhase,
  LatencyMetrics,
  LogEntry,
  LogLevel,
  LogSource,
  SessionStartResponse,
  SyncUpState,
  Transcript,
  Tuning,
} from "@/lib/types";

export interface AudioLevels {
  mic: number; // 0..1
  agent: number; // 0..1
  micBins: Uint8Array | null;
  agentBins: Uint8Array | null;
}

export const nowTs = () => {
  const d = new Date();
  const p = (n: number, w = 2) => String(n).padStart(w, "0");
  return `${p(d.getHours())}:${p(d.getMinutes())}:${p(d.getSeconds())}.${p(d.getMilliseconds(), 3)}`;
};

async function api<T>(path: string, body?: unknown): Promise<T> {
  const res = await fetch(`${BACKEND_URL}${path}`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: body === undefined ? undefined : JSON.stringify(body),
  });
  const data = await res.json().catch(() => ({}));
  if (!res.ok) throw new Error(data?.detail || `${path} failed (${res.status})`);
  return data as T;
}

/** Speaker Echo Guard: agent louder than this (getVolumeLevel 0..1) => worker mic is paused. */
const ECHO_GUARD_LEVEL = 0.1;
/** ...and stays paused until the agent has been quiet this long. */
const ECHO_GUARD_HANG_MS = 250;
const LOCAL_UID = "1001";

export function useAgoraSession() {
  // A fresh "lobby" channel per page load; every live call then gets its own brand-new channel from the backend,
  // so a leftover agent from an earlier call can never talk into the current one.
  const [channel, setChannel] = useState(() => `${CHANNEL_NAME}-lobby-${Date.now().toString(36)}`);
  const [state, setState] = useState<SyncUpState | null>(null);
  const [phase, setPhase] = useState<CallPhase>("idle");
  const [error, setError] = useState<string | null>(null);
  const [micMuted, setMicMuted] = useState(false);
  const [streamOnline, setStreamOnline] = useState(false);
  const [clientLogs, setClientLogs] = useState<LogEntry[]>([]);
  const [liveTranscripts, setLiveTranscripts] = useState<Transcript[]>([]);
  const [agentState, setAgentState] = useState<AgentState>("idle");
  const [latency, setLatency] = useState<LatencyMetrics>({});
  const [rtmOnline, setRtmOnline] = useState(false);
  const [tuning, setTuning] = useState<Tuning | null>(null);
  const [engPhase, setEngPhase] = useState<"idle" | "joining" | "on_call">("idle");
  const [echoGuard, setEchoGuardState] = useState(true); // on by default: laptop/stage speakers
  const [guardMuting, setGuardMuting] = useState(false);

  const channelRef = useRef(channel);
  channelRef.current = channel;

  // Worker call
  const clientRef = useRef<IAgoraRTCClient | null>(null);
  const isConnectingRef = useRef(false); // single-instance lock: StrictMode / double clicks never spawn 2 clients
  const rtmRef = useRef<any>(null);
  const micRef = useRef<IMicrophoneAudioTrack | null>(null);
  const agentTrackRef = useRef<IRemoteAudioTrack | null>(null);
  const agentIdRef = useRef<string | null>(null);
  // Outbound engineer call: a second Agora RTC client acts as the engineer's handset.
  const engClientRef = useRef<IAgoraRTCClient | null>(null);
  const engConnectingRef = useRef(false);
  const engMicRef = useRef<IMicrophoneAudioTrack | null>(null);
  const engTrackRef = useRef<IRemoteAudioTrack | null>(null);
  // Mic mute model: user mute OR echo-guard pause OR worker-on-hold.
  const userMutedRef = useRef(false);
  const guardRef = useRef(false);
  const echoGuardRef = useRef(true);
  const agentStateRef = useRef<AgentState>("idle");

  const ctxRef = useRef<AudioContext | null>(null);
  const micAnalyserRef = useRef<AnalyserNode | null>(null);
  const agentAnalyserRef = useRef<AnalyserNode | null>(null);
  const micBins = useRef<Uint8Array<ArrayBuffer> | null>(null);
  const agentBins = useRef<Uint8Array<ArrayBuffer> | null>(null);
  const assembler = useRef(new ChunkAssembler());
  const loggedFinals = useRef(new Set<string>());
  const seq = useRef(0);

  const addLog = useCallback((level: LogLevel, source: LogSource, message: string) => {
    seq.current += 1;
    setClientLogs((prev) => [...prev.slice(-200), { id: `web-${seq.current}`, ts: nowTs(), level, source, message }]);
  }, []);

  /** Single place that decides whether each local mic sends audio. Local tracks are never .play()-ed. */
  const applyMicMute = useCallback(() => {
    const onEngineerCall = !!engMicRef.current;
    micRef.current?.setMuted(userMutedRef.current || guardRef.current || onEngineerCall).catch(() => undefined);
    engMicRef.current?.setMuted(userMutedRef.current || guardRef.current).catch(() => undefined);
  }, []);

  // ---------------------------------------------------------------- live epistemic state + pipeline logs (SSE)
  useEffect(() => {
    const es = new EventSource(`${BACKEND_URL}/api/session/${encodeURIComponent(channel)}/stream`);
    es.addEventListener("state", (ev) => {
      try {
        setState(JSON.parse((ev as MessageEvent).data));
        setStreamOnline(true);
      } catch {
        /* ignore malformed frame */
      }
    });
    es.onerror = () => setStreamOnline(false);
    return () => es.close();
  }, [channel]);

  // ---------------------------------------------------------------- agent → client events (RTM primary, RTC fallback)
  const upsertTranscript = useCallback((id: string, patch: Omit<Transcript, "id" | "ts">) => {
    setLiveTranscripts((prev) => {
      const i = prev.findIndex((t) => t.id === id);
      if (i === -1) return [...prev.slice(-80), { id, ts: nowTs(), ...patch }];
      if (prev[i].text === patch.text && prev[i].isFinal === patch.isFinal && prev[i].interrupted === patch.interrupted) return prev;
      const next = prev.slice();
      next[i] = { ...next[i], ...patch };
      return next;
    });
  }, []);

  const logFinalOnce = useCallback(
    (id: string, source: LogSource, line: string, level: LogLevel = "INFO") => {
      if (loggedFinals.current.has(id)) return;
      loggedFinals.current.add(id);
      addLog(level, source, line);
    },
    [addLog],
  );

  const setAgentStateBoth = useCallback((s: AgentState) => {
    agentStateRef.current = s;
    setAgentState(s);
  }, []);

  const handleEvent = useCallback(
    (ev: AgentEvent) => {
      switch (ev.kind) {
        case "user_transcript": {
          if (!ev.text.trim()) return;
          const id = `w-${ev.turnId}`;
          upsertTranscript(id, { role: "worker", text: ev.text, isFinal: ev.final, source: "rtm" });
          if (ev.final) logFinalOnce(id, "ASR", `Worker: ${ev.text}`);
          break;
        }
        case "agent_transcript": {
          if (!ev.text.trim()) return;
          const id = `a-${ev.turnId}`;
          const done = ev.status !== "in_progress";
          upsertTranscript(id, { role: "agent", text: ev.text, isFinal: done, interrupted: ev.status === "interrupted", source: "rtm" });
          if (done) logFinalOnce(id, "TTS", `SyncUp: ${ev.text}${ev.status === "interrupted" ? " [interrupted]" : ""}`);
          break;
        }
        case "interrupt":
          addLog("ACTION", "RTC", `Barge-in detected: agent turn ${ev.turnId} cut off, listening`);
          setLiveTranscripts((prev) => prev.map((t) => (t.id === `a-${ev.turnId}` ? { ...t, interrupted: true, isFinal: true } : t)));
          break;
        case "metric":
          if (["asr", "llm", "tts"].includes(ev.module) && Number.isFinite(ev.latencyMs)) {
            setLatency((l) => ({ ...l, [ev.module]: Math.round(ev.latencyMs) }));
          }
          break;
        case "turn_finished":
          if (ev.e2eMs) {
            setLatency((l) => ({ ...l, e2e: Math.round(ev.e2eMs!) }));
            addLog("INFO", "RTC", `Turn ${ev.turnId ?? ""} end-to-end latency ${Math.round(ev.e2eMs)} ms`);
          }
          break;
        case "state":
          if (ev.state) setAgentStateBoth(ev.state as AgentState);
          break;
        case "error":
          addLog("WARN", "RTC", `Agent ${ev.module} error ${ev.code}: ${ev.message}`);
          break;
      }
    },
    [addLog, logFinalOnce, upsertTranscript, setAgentStateBoth],
  );

  const handleRaw = useCallback(
    (raw: unknown) => {
      const ev = parseAgentMessage(raw);
      if (ev) handleEvent(ev);
    },
    [handleEvent],
  );

  // ---------------------------------------------------------------- audio analysis
  const makeAnalyser = useCallback((track: MediaStreamTrack): AnalyserNode | null => {
    const ctx = ctxRef.current;
    if (!ctx) return null;
    try {
      const src = ctx.createMediaStreamSource(new MediaStream([track]));
      const analyser = ctx.createAnalyser();
      analyser.fftSize = 128;
      analyser.smoothingTimeConstant = 0.72;
      src.connect(analyser); // analysis only, never routed to speakers
      return analyser;
    } catch {
      return null;
    }
  }, []);

  /** Polled by the visualizer every animation frame (no React re-render). */
  const getLevels = useCallback((): AudioLevels => {
    const read = (a: AnalyserNode | null, buf: React.MutableRefObject<Uint8Array<ArrayBuffer> | null>) => {
      if (!a) return null;
      if (!buf.current || buf.current.length !== a.frequencyBinCount) buf.current = new Uint8Array(a.frequencyBinCount);
      a.getByteFrequencyData(buf.current);
      return buf.current;
    };
    const micLive = !!micRef.current && !micMuted && !guardRef.current;
    return {
      mic: micLive ? micRef.current!.getVolumeLevel() : 0,
      agent: agentTrackRef.current ? agentTrackRef.current.getVolumeLevel() : 0,
      micBins: micLive ? read(micAnalyserRef.current, micBins) : null,
      agentBins: read(agentAnalyserRef.current, agentBins),
    };
  }, [micMuted]);

  // ---------------------------------------------------------------- Speaker Echo Guard (half-duplex)
  // On laptop speakers the agent's Murf voice re-enters the mic and the agent hears itself ("voice mixing").
  // While the agent is audibly speaking, pause the mic; resume 250 ms after it goes quiet. Headphones: turn off
  // for instant barge-in. Uses the remote track's own level (Agora's volume-indicator event only fires every 2 s).
  useEffect(() => {
    if (phase !== "live" && engPhase !== "on_call") return;
    let lastLoud = 0;
    const id = setInterval(() => {
      const track = engClientRef.current ? engTrackRef.current : agentTrackRef.current;
      const level = track?.getVolumeLevel() ?? 0;
      const now = performance.now();
      const speaking = level > ECHO_GUARD_LEVEL || (!engClientRef.current && agentStateRef.current === "speaking");
      if (echoGuardRef.current && speaking) lastLoud = now;
      const shouldMute = echoGuardRef.current && now - lastLoud < ECHO_GUARD_HANG_MS;
      if (shouldMute !== guardRef.current) {
        guardRef.current = shouldMute;
        setGuardMuting(shouldMute);
        applyMicMute();
      }
    }, 50);
    return () => {
      clearInterval(id);
      if (guardRef.current) {
        guardRef.current = false;
        setGuardMuting(false);
        applyMicMute();
      }
    };
  }, [phase, engPhase, applyMicMute]);

  const setEchoGuard = useCallback(
    (on: boolean) => {
      echoGuardRef.current = on;
      setEchoGuardState(on);
      addLog("INFO", "RTC", on ? "Speaker Echo Guard ON: mic pauses while SyncUp speaks (laptop speakers)" : "Speaker Echo Guard OFF: full-duplex barge-in (use headphones)");
    },
    [addLog],
  );

  /** Subscribe to exactly one remote agent track per client; ignore our own uid; replace (never stack) tracks. */
  const attachAgentAudio = useCallback(
    async (client: IAgoraRTCClient, user: IAgoraRTCRemoteUser, slot: React.MutableRefObject<IRemoteAudioTrack | null>, onNew?: (t: IRemoteAudioTrack) => void) => {
      if (String(user.uid) === LOCAL_UID) return;
      await client.subscribe(user, "audio");
      const track = user.audioTrack;
      if (!track) return;
      if (slot.current && slot.current !== track) slot.current.stop(); // never two agent voices at once
      slot.current = track;
      track.play();
      onNew?.(track);
    },
    [],
  );

  // ---------------------------------------------------------------- lifecycle
  const teardownMedia = useCallback(async () => {
    micRef.current?.stop();
    micRef.current?.close();
    micRef.current = null;
    agentTrackRef.current?.stop();
    agentTrackRef.current = null;
    micAnalyserRef.current = null;
    agentAnalyserRef.current = null;
    try {
      await clientRef.current?.leave();
    } catch {
      /* already gone */
    }
    clientRef.current?.removeAllListeners();
    clientRef.current = null;
    const rtm = rtmRef.current;
    rtmRef.current = null;
    if (rtm) await rtm.logout().catch(() => undefined);
    setRtmOnline(false);
    await ctxRef.current?.close().catch(() => undefined);
    ctxRef.current = null;
    setAgentStateBoth("idle");
  }, [setAgentStateBoth]);

  const teardownEngineer = useCallback(async () => {
    engMicRef.current?.stop();
    engMicRef.current?.close();
    engMicRef.current = null;
    engTrackRef.current?.stop();
    engTrackRef.current = null;
    try {
      await engClientRef.current?.leave();
    } catch {
      /* already gone */
    }
    engClientRef.current?.removeAllListeners();
    engClientRef.current = null;
    engConnectingRef.current = false;
    agentTrackRef.current?.setVolume(100); // worker call off hold
    applyMicMute();
    setEngPhase("idle");
  }, [applyMicMute]);

  /** Presenter shortcut / approval: finish triage and make the lead engineer's phone ring. */
  const ringEngineer = useCallback(async () => {
    try {
      await api("/api/engineer/ring", { channel_name: channelRef.current });
      addLog("ACTION", "ROUTE", "Triage finished - ringing the lead engineer");
    } catch (e) {
      setError((e as Error).message);
    }
  }, [addLog]);

  /** Green Answer: the worker call hands over (backend stops its agent), the browser becomes the engineer's handset,
   *  and the engineer agent speaks first with the verified incident summary. */
  const answerEngineer = useCallback(
    async (language: string = "en-IN") => {
      if (engClientRef.current || engConnectingRef.current) return;
      engConnectingRef.current = true;
      setEngPhase("joining");
      try {
        const r = await api<{ simulated?: boolean; app_id: string; channel_name: string; uid: number; rtc_token: string }>(
          "/api/engineer/answer",
          { channel_name: channelRef.current, language },
        );
        if (r.simulated) {
          setEngPhase("idle");
          return;
        }
        if (clientRef.current) {
          await teardownMedia(); // worker call handed over (its agent was stopped server-side)
          agentIdRef.current = null;
          setPhase("idle");
        }
        const AgoraRTC = (await import("agora-rtc-sdk-ng")).default;
        const client = AgoraRTC.createClient({ mode: "rtc", codec: "vp8" });
        engClientRef.current = client;
        client.on("user-published", (user, mediaType) => {
          if (mediaType !== "audio") return;
          void attachAgentAudio(client, user, engTrackRef, () =>
            addLog("ACTION", "RTC", "Engineer line connected - SyncUp Dispatch briefing (Murf Falcon 2.1)"),
          );
        });
        await client.join(r.app_id, r.channel_name, r.rtc_token || null, r.uid);
        const mic = await AgoraRTC.createMicrophoneAudioTrack({ encoderConfig: "speech_standard", AEC: true, ANS: true, AGC: true });
        engMicRef.current = mic;
        applyMicMute();
        await client.publish(mic);
        setEngPhase("on_call");
      } catch (e) {
        setError(`Engineer call: ${(e as Error).message}`);
        await teardownEngineer();
      } finally {
        engConnectingRef.current = false;
      }
    },
    [addLog, applyMicMute, attachAgentAudio, teardownEngineer, teardownMedia],
  );

  const declineEngineer = useCallback(async () => {
    await teardownEngineer();
    await api("/api/engineer/decline", { channel_name: channelRef.current }).catch(() => undefined);
  }, [teardownEngineer]);

  const confirmDispatch = useCallback(async () => {
    try {
      await api("/api/engineer/confirm", { channel_name: channelRef.current });
    } catch (e) {
      setError((e as Error).message);
    }
  }, []);

  const hangUpEngineer = useCallback(async () => {
    await teardownEngineer();
    await api(`/api/session/${encodeURIComponent(channelRef.current)}/escalation/end`).catch(() => undefined);
    addLog("INFO", "RTC", "Engineer call ended - back to the worker");
  }, [addLog, teardownEngineer]);

  const getEngineerLevel = useCallback(() => engTrackRef.current?.getVolumeLevel() ?? 0, []);

  const stop = useCallback(async () => {
    setPhase("ending");
    await teardownEngineer();
    try {
      await api("/api/session/stop", { channel_name: channelRef.current, agent_id: agentIdRef.current });
    } catch (e) {
      addLog("WARN", "RTC", `Stop request failed: ${(e as Error).message}`);
    }
    await teardownMedia();
    agentIdRef.current = null;
    userMutedRef.current = false;
    setMicMuted(false);
    setPhase("idle");
    addLog("INFO", "RTC", "Left Agora channel, microphone released");
  }, [addLog, teardownMedia, teardownEngineer]);

  /** Start a fresh demo: hang up everything and move to a brand-new lobby channel (state resets to QR_READY). */
  const resetDemo = useCallback(async () => {
    await teardownEngineer();
    if (clientRef.current) await teardownMedia();
    agentIdRef.current = null;
    setPhase("idle");
    setLiveTranscripts([]);
    setLatency({});
    setError(null);
    const next = `${CHANNEL_NAME}-lobby-${Date.now().toString(36)}`;
    channelRef.current = next;
    setChannel(next);
  }, [teardownEngineer, teardownMedia]);

  const connectRtm = useCallback(
    async (s: SessionStartResponse) => {
      try {
        const AgoraRTM: any = (await import("agora-rtm-sdk")).default;
        const rtm = new AgoraRTM.RTM(s.app_id, String(s.uid));
        rtm.addEventListener("message", (e: any) => {
          if (e?.channelName && e.channelName !== s.channel_name) return; // only this call's channel
          handleRaw(decodePayload(e.message));
        });
        rtm.addEventListener("presence", (e: any) => {
          const st = e?.stateChanged?.state;
          if (typeof st === "string" && st) setAgentStateBoth(st as AgentState);
        });
        await rtm.login(s.rtm_token ? { token: s.rtm_token } : undefined);
        await rtm.subscribe(s.channel_name, { withMessage: true, withPresence: true });
        rtmRef.current = rtm;
        setRtmOnline(true);
        addLog("INFO", "RTC", "RTM signaling subscribed: live transcripts, agent state & latency metrics");
      } catch (e) {
        addLog("WARN", "RTC", `RTM unavailable (${(e as Error).message || e}); backend REST history keeps captions live`);
      }
    },
    [addLog, handleRaw, setAgentStateBoth],
  );

  const start = useCallback(
    async (language: string, assetHint: string, environment: string) => {
      if (isConnectingRef.current || clientRef.current) return; // single-instance lock
      isConnectingRef.current = true;
      setError(null);
      setPhase("connecting");
      setLiveTranscripts([]);
      setLatency({});
      loggedFinals.current.clear();
      ctxRef.current = new AudioContext(); // created inside the click gesture so it is allowed to run
      addLog("INFO", "RTC", `Requesting ConvoAI agent (${language}, ${environment}, scenario ${assetHint}) on a fresh channel...`);
      let session: SessionStartResponse | null = null;
      try {
        session = await api<SessionStartResponse>("/api/session/start", {
          channel_name: "auto",
          previous_channel: channelRef.current,
          language,
          asset_hint: assetHint,
          environment,
        });
        agentIdRef.current = session.agent_id;
        setTuning(session.tuning ?? null);
        channelRef.current = session.channel_name;
        setChannel(session.channel_name); // state stream follows the new channel

        // 1) RTM first, so the agent's greeting transcript is not missed.
        await connectRtm(session);

        // 2) RTC: exactly one client, one subscribed agent track, one published mic.
        const AgoraRTC = (await import("agora-rtc-sdk-ng")).default;
        AgoraRTC.setLogLevel(3);
        const client = AgoraRTC.createClient({ mode: "rtc", codec: "vp8" });
        clientRef.current = client;

        client.on("user-published", (user, mediaType) => {
          if (mediaType !== "audio") return;
          void attachAgentAudio(client, user, agentTrackRef, (track) => {
            agentAnalyserRef.current = makeAnalyser(track.getMediaStreamTrack());
            if (engClientRef.current) track.setVolume(0); // still on hold
            addLog("ACTION", "RTC", `Agent audio subscribed (uid ${user.uid}) - Murf Falcon stream playing`);
          });
        });
        client.on("user-unpublished", (user) => addLog("INFO", "RTC", `Agent uid ${user.uid} paused audio`));
        client.on("user-left", (user) => addLog("WARN", "RTC", `Agent uid ${user.uid} left the channel`));
        client.on("stream-message", (_uid: unknown, payload: Uint8Array) => {
          if (rtmRef.current) return; // RTM is primary; avoid double-processing
          handleRaw(assembler.current.push(new TextDecoder().decode(payload)));
        });
        client.on("connection-state-change", (cur, _prev, reason) => {
          if (cur === "DISCONNECTED" && reason && reason !== "LEAVE") addLog("WARN", "RTC", `RTC disconnected: ${reason}`);
        });

        await client.join(session.app_id, session.channel_name, session.rtc_token || null, session.uid);
        addLog("INFO", "RTC", `Joined ${session.channel_name} as uid ${session.uid}`);

        // Acoustic front-end: AEC stops Murf audio from the speakers re-entering ARES; ANS removes floor hum;
        // AGC + per-environment gain lift soft voices. The local track is published, never played locally.
        const mic = await AgoraRTC.createMicrophoneAudioTrack({ encoderConfig: "speech_standard", AEC: true, ANS: true, AGC: true });
        mic.setVolume(Math.max(0, Math.min(1000, session.client_mic_gain ?? 100)));
        micRef.current = mic;
        micAnalyserRef.current = makeAnalyser(mic.getMediaStreamTrack());
        applyMicMute();
        await client.publish(mic);
        addLog("ACTION", "RTC", `Mic published (AEC+ANS+AGC, gain ${session.client_mic_gain ?? 100}%, echo guard ${echoGuardRef.current ? "on" : "off"}) - speak now`);
        setAgentStateBoth("listening");
        setPhase("live");
      } catch (e) {
        const msg = (e as Error).message || String(e);
        setError(msg);
        addLog("WARN", "RTC", `Start failed: ${msg}`);
        if (session) {
          await api("/api/session/stop", { channel_name: session.channel_name, agent_id: session.agent_id }).catch(() => undefined);
        }
        await teardownMedia();
        setPhase("idle");
      } finally {
        isConnectingRef.current = false;
      }
    },
    [addLog, applyMicMute, attachAgentAudio, connectRtm, handleRaw, makeAnalyser, setAgentStateBoth, teardownMedia],
  );

  const simulate = useCallback(async () => {
    setError(null);
    setLiveTranscripts([]);
    setLatency({});
    try {
      await api(`/api/session/${encodeURIComponent(channelRef.current)}/simulate?pace=1.2`);
      addLog("INFO", "RTC", "Demo Sim requested (scripted Malayalam LINE-03 run)");
    } catch (e) {
      setError((e as Error).message);
    }
  }, [addLog]);

  // CONFIRM -> AFTER: supervisor override, same backend path as the worker's spoken "yes".
  const approve = useCallback(async () => {
    try {
      await api(`/api/session/${encodeURIComponent(channelRef.current)}/approve`);
      addLog("ACTION", "ROUTE", "Supervisor pressed Approve & Route Ticket");
    } catch (e) {
      setError((e as Error).message);
    }
  }, [addLog]);

  // BEFORE: QR scan on the machine pre-loads its maintenance history into the session.
  const scanQr = useCallback(async (assetId: string) => {
    try {
      await api(`/api/session/${encodeURIComponent(channelRef.current)}/context`, { asset_id: assetId, source: "qr" });
    } catch (e) {
      setError((e as Error).message);
    }
  }, []);

  const toggleMic = useCallback(async () => {
    const next = !userMutedRef.current;
    userMutedRef.current = next;
    setMicMuted(next);
    applyMicMute();
    addLog("INFO", "RTC", next ? "Microphone muted" : "Microphone live");
  }, [addLog, applyMicMute]);

  // Release mic + leave channels if the tab unmounts mid-call.
  useEffect(() => () => void teardownMedia().then(teardownEngineer), [teardownMedia, teardownEngineer]);

  const rtmCaptions = liveTranscripts.length > 0;

  const logs = useMemo(() => {
    const server = (state?.logs ?? []).filter((l) => !(rtmCaptions && l.id.startsWith("hist-")));
    const merged = [...server, ...clientLogs];
    return merged.sort((a, b) => (a.ts < b.ts ? -1 : a.ts > b.ts ? 1 : 0));
  }, [state?.logs, clientLogs, rtmCaptions]);

  const transcripts = useMemo(() => {
    // RTM captions stream word by word; if RTM is down, the backend's history sync keeps the chat live.
    const server = (state?.transcripts ?? []).filter((t) => !(rtmCaptions && t.source === "history"));
    const merged = [...server, ...liveTranscripts];
    return merged.sort((a, b) => (a.ts < b.ts ? -1 : a.ts > b.ts ? 1 : 0));
  }, [state?.transcripts, liveTranscripts, rtmCaptions]);

  return {
    channel,
    state,
    phase,
    error,
    micMuted,
    streamOnline,
    rtmOnline,
    logs,
    transcripts,
    agentState,
    latency,
    start,
    stop,
    simulate,
    approve,
    scanQr,
    engPhase,
    ringEngineer,
    answerEngineer,
    declineEngineer,
    confirmDispatch,
    hangUpEngineer,
    resetDemo,
    getEngineerLevel,
    echoGuard,
    setEchoGuard,
    guardMuting,
    tuning,
    toggleMic,
    getLevels,
  };
}
