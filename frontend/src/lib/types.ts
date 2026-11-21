// BEFORE_CONTEXT -> INVESTIGATING -> AWAITING_APPROVAL -> ROUTED (+ ERROR_HANDLED), mirrors backend state_store
export type SessionStatus = "BEFORE_CONTEXT" | "INVESTIGATING" | "AWAITING_APPROVAL" | "ROUTED" | "ERROR_HANDLED";
export type LogLevel = "INFO" | "WARN" | "ACTION";
export type LogSource = "RTC" | "ASR" | "TTS" | "TRIAGE" | "DB" | "ROUTE";

export interface LogEntry {
  id: string;
  ts: string;
  level: LogLevel;
  source: LogSource;
  message: string;
}

export interface TextItem {
  text: string;
  resolved?: boolean;
}

export interface DebunkedClaim extends TextItem {
  log_id: string;
  evidence: string;
}

export interface EnglishBrief {
  ticket_id: string;
  priority: "P1" | "P2" | "P3";
  asset: string;
  summary: string;
  verified_facts: string[];
  debunked_claims: string[];
  unverified_guesses: string[];
  open_unknowns: string[];
  recommended_action: string;
  spare_part_reserved: string | null;
  assigned_team: string;
  created_at: number;
  approved_via?: "voice" | "manual";
  follow_up?: string;
  follow_up_due_at?: number;
  ops_webhook?: "dispatched" | "logged";
  routed_at?: number;
}

/** Presentation flow shown on the phone mockup. */
export type DemoStage = "QR_READY" | "WORKER_CALL" | "ENGINEER_RINGING" | "ENGINEER_CONNECTED" | "DISPATCH_CONFIRMED";

export interface Engineer {
  name: string;
  first: string;
  honorific: string;
  role: string;
  team: string;
}

export type CallStatus = "dialing" | "ringing" | "connected" | "acknowledged" | "completed" | "failed";

/** AFTER stage: SyncUp's outbound English call to the on-call engineer. */
export interface Escalation {
  status: CallStatus;
  mode: "live" | "sim";
  engineer: Engineer;
  channel: string;
  agent_id: string | null;
  opener: string;
  transcripts: Transcript[];
  eta_minutes: number | null;
  accepted: boolean | null;
  notes: string;
  started_at: number;
  connected_at: number | null;
  ended_at?: number;
  ticket_id: string;
  language?: string;
}

export interface MaintenanceLog {
  log_id: string;
  date: string;
  component: string;
  status: string;
}

export interface AssetContext {
  asset_id: string;
  asset_name: string;
  source: "qr" | "scenario" | "lookup";
  loaded_at: number;
  maintenance_logs: MaintenanceLog[];
  sops: { code: string; fault: string; spare_part: string; team: string }[];
}

export interface Tuning {
  temperature: number;
  presence_penalty: number;
  voice: string;
  style: string;
  rate: number;
  pitch: number;
  volume_offset: number | null;
  vad_threshold: number;
  interrupt_ms: number;
  silence_ms: number;
}

export interface ActiveCheck {
  sop_code: string | null;
  question: string | null;
  directive: string;
}

export interface SyncUpState {
  channel: string;
  agent_id: string | null;
  status: SessionStatus;
  asset_id: string | null;
  language: string | null;
  asset_hint: string | null;
  active_check: ActiveCheck | null;
  verified_facts: TextItem[];
  unverified_guesses: TextItem[];
  debunked_claims: DebunkedClaim[];
  missing_unknowns: TextItem[];
  english_brief: EnglishBrief | null;
  asset_context: AssetContext | null;
  proposed_ticket: EnglishBrief | null;
  confirmation_question: string | null;
  escalation: Escalation | null;
  demo_stage: DemoStage;
  engineer_brief: { engineer: Engineer; spoken_summary: string; ticket_id: string; priority: string; asset_id: string | null } | null;
  worker_name: string | null;
  approval: { via: "voice" | "manual"; at: number } | null;
  follow_up_schedule: string | null;
  error: string | null;
  environment: string | null;
  simulated: boolean;
  transcripts: Transcript[];
  logs: LogEntry[];
  updated_at: number;
}

export interface SessionStartResponse {
  app_id: string;
  channel_name: string;
  uid: number;
  rtc_token: string;
  rtm_token: string;
  agent_id: string;
  language: string;
  asset_hint: string;
  environment: string;
  agent_uid: number;
  client_mic_gain: number;
  tuning: Tuning;
}

export type CallPhase = "idle" | "connecting" | "live" | "ending";

export type Role = "worker" | "agent" | "engineer";

export interface Transcript {
  id: string;
  role: Role;
  text: string;
  isFinal: boolean;
  ts: string;
  interrupted?: boolean;
  source?: "rtm" | "sim" | "history";
}

export type AgentState = "idle" | "listening" | "thinking" | "speaking" | "silent";

export interface LatencyMetrics {
  asr?: number;
  llm?: number;
  tts?: number;
  e2e?: number;
}

export type CheckStatus = "OK" | string;

export interface Preflight {
  agora_creds: boolean;
  agora_rest: CheckStatus;
  murf_api: CheckStatus;
  webhook_tunnel: CheckStatus;
  ready: boolean;
  hints: string[];
  elapsed_ms: number;
  llm: { credential_mode: string; model: string };
}
