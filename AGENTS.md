# AGENTS.md — Multilingual Voice SyncUp (Engineering & Architecture Contract)

> **STRICT DIRECTIVE FOR CODING AGENTS:**  
> You are building **Multilingual Voice SyncUp** for **Track 2: Voice AI at Work: Beyond the Call Center**.  
> Before writing, modifying, or refactoring any code, you **MUST** read this master specification in full and cross-reference the modular specification files listed in **Section 1** whenever working on their respective subsystems. Do **NOT** introduce third-party STT/TTS wrappers (no Deepgram, ElevenLabs, Sarvam, or Twilio). This system runs strictly on **Agora Conversational AI Engine** + **Murf.ai Falcon 2.1**.

---

## 1. Mandatory Reference Protocol (Modular `.md` Index)

Whenever your task touches a specific layer of the codebase, you **MUST** read and obey the corresponding specification file in `/docs/` before generating code:

1. **[`docs/AGORA_PIPELINE.md`](file:///c:/Users/Tilin%20Bijoy/Desktop/Agorahacks/docs/AGORA_PIPELINE.md)** — Refer to this before touching RTC/RTM token generation, Agora `/join` and `/leave` REST lifecycle endpoints, or RTM data-channel event broadcasting.
2. **[`docs/MURF_TTS_CONFIG.md`](file:///c:/Users/Tilin%20Bijoy/Desktop/Agorahacks/docs/MURF_TTS_CONFIG.md)** — Refer to this before modifying TTS parameters, Indian `voiceId` mappings, Falcon 2.1 WebSocket URLs, or Hindi/English code-mixed prosody rules.
3. **[`docs/VAD_LATENCY_TUNING.md`](file:///c:/Users/Tilin%20Bijoy/Desktop/Agorahacks/docs/VAD_LATENCY_TUNING.md)** — Refer to this before modifying `turn_detection`, `agora_vad` thresholds, barge-in timings, audio sample rates, or async background tasks.
4. **[`docs/EPISTEMIC_ENGINE.md`](file:///c:/Users/Tilin%20Bijoy/Desktop/Agorahacks/docs/EPISTEMIC_ENGINE.md)** — Refer to this before editing the `SyncUp` system prompt, the `Facts vs. Guesses vs. Contradictions` triage schema, company context lookup logic, or English ticket generation.
5. **[`docs/UI_COMMAND_CENTER.md`](file:///c:/Users/Tilin%20Bijoy/Desktop/Agorahacks/docs/UI_COMMAND_CENTER.md)** — Refer to this before building or styling any React/Next.js components, audio visualizers, live triage boards, or bilingual transcript feeds.

*If any file in `/docs/` does not yet exist during initial scaffolding, generate it first from the corresponding section of this `AGENTS.md` before writing application code.*

---

## 2. System Architecture & Real-Time Data Flow

Audio **NEVER** passes through the Python FastAPI backend. Agora's cloud edge orchestrates full-duplex WebRTC audio, built-in `ARES` ASR, LLM tool execution, and direct WebSocket streaming to Murf.ai's India edge server.

```text
┌─────────────────────────────────────────────────────────────────────────────┐
│                    FRONTEND (Next.js / React TypeScript)                    │
│  • agora-rtc-sdk-ng  ──► Publishes Worker Mic (16kHz/24kHz) & Plays TTS     │
│  • agora-rtm-sdk     ──► Subscribes to Live Transcripts & Triage JSON State │
│  • Command Center UI ──► Renders Facts / Guesses / Debunked / English Brief │
└───────────────┬─────────────────────────────────────────────▲───────────────┘
                │ (1) WebRTC Audio (UDP)                      │ (5) RTC Audio +
                ▼                                             │     RTM State Push
┌─────────────────────────────────────────────────────────────┴───────────────┐
│                  AGORA CONVERSATIONAL AI ENGINE (Cloud)                     │
│                                                                             │
│  ┌────────────────────────┐   ┌─────────────────────────┐   ┌────────────┐  │
│  │ Built-in ASR: ARES     │──►│ LLM + Native Tools      │──►│ Murf TTS   │  │
│  │ ("en-US,hi-IN" +       │   │ (Calls FastAPI Webhooks │   │ Falcon 2.1 │  │
│  │  Domain Keywords)      │   │  for SyncUp Triage)     │   │ (24kHz PCM)│  │
│  └────────────────────────┘   └────────────┬────────────┘   └──────┬─────┘  │
└────────────────────────────────────────────┼───────────────────────┼────────┘
                                             │ (3) HTTPS Tool Call   │ (4) WSS Stream
                                             ▼                       ▼
┌─────────────────────────────────────────────────────┐   ┌───────────────────┐
│             FASTAPI BACKEND (Python 3.11+)          │   │   MURF.AI CLOUD   │
│  • POST /api/config       -> RTC + RTM Token Gen    │   │   India Regional  │
│  • POST /api/agent/start  -> Agora ConvoAI /join    │   │   in.api.murf.ai  │
│  • POST /api/agent/stop   -> Agora ConvoAI /leave   │   │   (<100ms TTFA)   │
│  • POST /tools/triage     -> Fact/Guess + DB Check  │   └───────────────────┘
│  • POST /tools/route      -> Final English Brief    │
└─────────────────────────────────────────────────────┘
```

### End-to-End Sequence Walkthrough

```text
Worker Speaks (Hindi/Hinglish)
  │
  ├──► [WebRTC UDP] ──► Agora Cloud SDRTN
  │                        │
  │                        ├──► ARES ASR (Live Transcription: "en-US,hi-IN")
  │                        │       │
  │                        │       ├──► RTM 2.x Data Stream ──► UI Captions Feed
  │                        │       │
  │                        │       └──► LLM Reasoning Engine (GPT-4o-mini / Claude)
  │                        │               │
  │                        │               ├── [Tool Call: triage_statement]
  │                        │               │     │
  │                        │               │     └──► FastAPI /tools/triage (HTTPS)
  │                        │               │            │
  │                        │               │            ├── Verify with Ground Truth DB
  │                        │               │            ├── Categorize: Fact | Guess | Contradiction
  │                        │               │            └── Publish RTM Event ──► UI Board
  │                        │               │
  │                        │               └── [Text Stream Response]
  │                        │                       │
  │                        │                       └──► Murf Falcon 2.1 (WSS)
  │                        │                              │
  │                        │                              └──► 24kHz Raw PCM Audio
  │                        │                                      │
  │                        ◄──────────────────────────────────────┘
  ▼
Worker Hears Agent Audio (WebRTC Full-Duplex Playback < 500ms total latency)
```

---

## 3. Strict Boundary Rules & Invariants

| Component | Permitted Responsibilities | STRICTLY FORBIDDEN |
| :--- | :--- | :--- |
| **Frontend (Next.js)** | • WebRTC Mic capture & Agora RTC track publishing<br>• Agora RTM 2.x stream subscription<br>• Real-time reactive state rendering (Triage Board, Waveform, Brief) | • Direct calls to Murf AI API<br>• Audio transcoding or local STT/TTS processing<br>• Bypassing Agora ConvoAI for LLM calls |
| **FastAPI Backend** | • Dual Token Generation (RTC token + RTM token)<br>• Agora Agent Lifecycle orchestration (`/join`, `/leave`)<br>• Epistemic DB lookups & verification against company records<br>• Structured English Ticket generation & RTM broadcast | • Ingesting, streaming, or proxying raw audio bytes<br>• Running local heavyweight ML/ASR models<br>• Blocking conversational tool-call webhooks (>300ms) |
| **Agora Cloud Engine** | • Full-duplex WebRTC SDRTN transport<br>• Hardware VAD & Barge-in detection<br>• Multilingual ARES ASR (`en-US,hi-IN`)<br>• LLM tool dispatch & direct Murf WSS streaming | • Altering voice parameters mid-turn without instruction<br>• Dropping RTM transcript messages |
| **Murf Falcon 2.1** | • Sub-100ms streaming TTS synthesis at 24kHz PCM<br>• Indian English & Hindi code-mixed prosody execution | • Telephony 8kHz fallback<br>• Non-streaming REST audio batch generation |

---

## 4. Subsystem Contracts & Interface Manifest

### 4.1 Agora Conversational AI REST Engine (`docs/AGORA_PIPELINE.md`)
* **Endpoint (`v2`):** `POST https://api.agora.io/api/conversational-ai-agent/v2/projects/{appid}/join`
* **Auth:** HTTP Basic Auth `Authorization: Basic base64(CustomerKey:CustomerSecret)`.
* **Agent Payload:**
  * `properties.channel`: Dynamic session channel ID.
  * `properties.token`: RTC Token generated specifically for `agent_rtc_uid` (numeric string or uint32).
  * `properties.agent_rtc_uid`: Explicit numeric UID (e.g. `999999`).
  * `properties.remote_rtc_uids`: Array containing the user's numeric UID (e.g. `["100001"]`).
  * `properties.enable_string_uid`: `false`.
* **ASR Configuration:** Built-in `ARES` with `languages: ["en-US", "hi-IN"]` and custom industrial dictionary boost terms (`P&ID`, `SCADA`, `VFD`, `Hazmat`, `Lockout-Tagout`).
* **Lifecycle Teardown:** `POST https://api.agora.io/api/conversational-ai-agent/v2/projects/{appid}/leave` with `{ "agent_id": "<active_agent_id>" }`.

### 4.2 Murf.ai Falcon 2.1 Engine (`docs/MURF_TTS_CONFIG.md`)
* **Engine Type:** Streaming WebSocket TTS (`model: "FALCON"`).
* **Base URL:** `wss://in.api.murf.ai/v1/speech/stream-input` (India regional low-latency edge).
* **Sample Rate:** `24000` (24kHz 16-bit Mono Linear PCM).
* **Target Latency:** Sub-100ms Time-to-First-Audio (TTFA).
* **Voice Profiles (Indian Accents & Code-Mixing):**
  * Primary Hindi/Hinglish Voice: `hi-IN-kabir` or `hi-IN-ananya`.
  * Primary Indian English Voice: `en-IN-eashan` or `en-IN-neerja`.
* **Prosody Constraints:** Natural conversational cadence; code-mixed sentences must maintain steady intonation without pitch breakage at language switches.

### 4.3 VAD & Turn-Taking Latency Tuning (`docs/VAD_LATENCY_TUNING.md`)
* **Voice Activity Detection:** Built-in `agora_vad`.
* **Turn Detection Window:**
  * `prefix_padding_ms`: `300`
  * `silence_duration_ms`: `350` (Prevents awkward pauses while avoiding premature cutoff during hesitant technical thinking).
  * `speech_threshold`: `0.5`
* **Barge-in / Interruption:**
  * Enabled: `true`.
  * On worker speech onset detection, Agora SDRTN immediately cancels downstream Murf Falcon audio packets and flushes local browser jitter buffers within `<80ms`.
* **Total Latency Budget:** User silence to first TTS audio frame: `< 480ms`.

### 4.4 Epistemic Engine & Triage Specifications (`docs/EPISTEMIC_ENGINE.md`)
* **Target Scenario:** Shift standup, field maintenance handover, construction & shopfloor sync-up.
* **Epistemic Classification Taxonomy:**
  1. **FACT (T-1):** Observed, verified, timestamped, or database-grounded assertion (e.g., *"Boiler 3 gauge reading 4.2 bar at 08:00"*).
  2. **GUESS (T-2):** Speculative, subjective, unmeasured inference (e.g., *"Lagta hai bypass valve stuck hai"* / *"Maybe electrical fault hai"*).
  3. **CONTRADICTION / DEBUNKED (T-3):** Assertion conflicting with verified DB records or earlier confirmed facts (e.g., *"Line 2 running"* when IoT/SCADA reports downtime).
* **SyncUp Clarification Loop:**
  * If a **GUESS** is detected: The agent asks a targeted, polite follow-up in code-mixed Hinglish: *"Aapne kaha valve stuck ho sakti hai — kya physical inspection kiya tha ya acoustic check?"*
  * If a **CONTRADICTION** is detected: The agent immediately flags it against company ground truth: *"Maintenance log ke mutabiq Line 2 shutdown par hai. Kya kisi ne override enable kiya?"*
* **Tool Calling Contract:**
  * Tool 1: `triage_statement(statement: str, category: "fact"|"guess"|"contradiction", confidence: float, contradiction_reason?: str, clarification_prompt?: str)`
  * Tool 2: `route_syncup_ticket(session_id: str, title: str, facts: list[str], unverified_guesses: list[str], flagged_contradictions: list[str], action_items: list[dict], priority: str)`

### 4.5 Frontend Command Center Architecture (`docs/UI_COMMAND_CENTER.md`)
* **Framework:** Next.js 14+ (App Router), TypeScript, Tailwind CSS, Lucide React, Framer Motion.
* **Agora SDKs:** `agora-rtc-sdk-ng` (^4.22.0) and `agora-rtm-sdk` (^2.2.0).
* **UI Modules:**
  1. **Session Control Bar:** Instant Connect/Disconnect, Channel status, TTFA latency indicator, Mic toggle, Audio input selector.
  2. **Live Waveform & Audio Visualizer:** Dual 60fps canvas visualizer showing Worker mic input and Agent Murf TTS output via Web Audio API `AnalyserNode`.
  3. **Real-Time Bilingual Transcript Stream:** Speech bubbles with language tag (`[HI]`, `[EN]`, `[HINGLISH]`), live streaming text, and speaker avatars.
  4. **Dynamic 3-Column Triage Board:**
     * Column 1: **Verified Facts** (Emerald green glow, badge tags).
     * Column 2: **Unverified Guesses** (Amber glow, interactive "Verify" button).
     * Column 3: **Contradictions / Debunked** (Rose red glow, ground truth reference badge).
  5. **Live Executive Brief & Action Router:** Auto-compiled English incident ticket with priority score, assignee recommendations, and one-click Jira/ERP/PDF export.

---

## 5. Complete Backend API Contract (FastAPI Python 3.11+)

The backend provides five core endpoints under `/api` and `/tools`:

```text
POST /api/config
  ├── Request:  { "channel": "syncup-field-101", "uid": "100001" }
  └── Response: { "app_id": "...", "channel": "...", "rtc_token": "...", "rtm_token": "...", "agent_uid": "999999" }

POST /api/agent/start
  ├── Request:  { "channel": "syncup-field-101", "user_uid": "100001" }
  └── Response: { "agent_id": "agent-xyz-890", "status": "STARTING", "channel": "syncup-field-101" }

POST /api/agent/stop
  ├── Request:  { "agent_id": "agent-xyz-890" }
  └── Response: { "agent_id": "agent-xyz-890", "status": "STOPPED" }

POST /tools/triage  (Called by Agora LLM Orchestrator via Webhook)
  ├── Request:  { "session_id": "...", "statement": "...", "category": "guess", "speaker": "worker" }
  └── Response: { "status": "recorded", "db_matched": false, "clarification_suggestion": "..." }

POST /tools/route   (Called by Agora LLM Orchestrator at Session End)
  ├── Request:  { "session_id": "...", "summary": "...", "facts": [...], "guesses": [...], "contradictions": [...] }
  └── Response: { "ticket_id": "TICK-9082", "status": "routed", "english_brief": "..." }
```

---

## 6. Directory Layout & Source Code Organization

```text
Agorahacks/
├── AGENTS.md                          # Master Architecture & Engineering Contract (This file)
├── .env.example                       # Reference environment variables
├── README.md                          # Hackathon track overview & quickstart guide
├── docs/                              # Modular Engineering Specifications
│   ├── AGORA_PIPELINE.md              # Agora RTC/RTM & ConvoAI REST specs
│   ├── MURF_TTS_CONFIG.md             # Murf Falcon 2.1 streaming TTS specs
│   ├── VAD_LATENCY_TUNING.md          # Latency budget, VAD & barge-in tuning
│   ├── EPISTEMIC_ENGINE.md            # Facts vs Guesses prompt & schemas
│   └── UI_COMMAND_CENTER.md           # Next.js Command Center design specs
├── backend/                           # FastAPI Service (Python 3.11+)
│   ├── requirements.txt               # Dependencies (fastapi, uvicorn, agora-token-builder, etc.)
│   ├── app/
│   │   ├── main.py                    # FastAPI application initialization & middleware
│   │   ├── config.py                  # Pydantic Settings & environment validation
│   │   ├── routers/
│   │   │   ├── agora.py               # /api/config, /api/agent/start, /api/agent/stop
│   │   │   └── tools.py               # /tools/triage, /tools/route (LLM Webhooks)
│   │   ├── services/
│   │   │   ├── agora_client.py        # Agora REST client & token builder
│   │   │   ├── epistemic_service.py   # Ground truth DB lookup & contradiction checks
│   │   │   └── rtm_broadcaster.py     # RTM 2.x event publisher to frontend
│   │   └── models/
│   │       ├── schemas.py             # Pydantic request & response models
│   │       └── company_context.py     # Ground truth domain data (equipment, logs, shifts)
└── frontend/                          # Next.js 14+ TypeScript Client
    ├── package.json                   # Dependencies (agora-rtc-sdk-ng, agora-rtm, lucide, tailwind)
    ├── tsconfig.json
    ├── tailwind.config.js
    ├── src/
    │   ├── app/
    │   │   ├── layout.tsx             # Root layout with dark mode theme
    │   │   └── page.tsx               # Command Center main page
    │   ├── components/
    │   │   ├── AudioVisualizer.tsx    # 60fps Web Audio API waveform visualizer
    │   │   ├── ControlBar.tsx         # Mic, Connect, TTFA latency telemetry
    │   │   ├── TranscriptFeed.tsx     # Live bilingual Hinglish/English captions
    │   │   ├── TriageBoard.tsx        # 3-column Facts / Guesses / Debunked board
    │   │   └── ExecutiveTicket.tsx    # Live generated English management brief
    │   ├── hooks/
    │   │   ├── useAgoraRTC.ts         # Mic publishing, audio track, playback
    │   │   └── useAgoraRTM.ts         # Real-time data channel listener
    │   └── lib/
    │       ├── agora-config.ts        # Client constants & credentials helper
    │       └── types.ts               # Shared TypeScript interfaces
```

---

## 7. Security, Environment & BYOK Invariants

1. **Credentials Isolation:** Never commit `.env` or production credentials. Client browser only receives short-lived channel RTC/RTM tokens.
2. **Murf API Key Protection:** The `MURF_API_KEY` is registered directly into Agora's Conversational AI Engine credential vault or submitted server-side during the `/join` agent payload. It is **NEVER** exposed to client browsers.
3. **Agora Customer Credentials:** Agora Customer ID and Customer Secret are used exclusively server-side in `backend/app/services/agora_client.py` using Base64 Basic Auth.
4. **CORS Policy:** FastAPI backend enforces explicit CORS origins for the frontend local and production deployment domains.

---

## 8. Acceptance Criteria Checklist

Before declaring any phase or feature complete, verify:
- [ ] **Zero 3rd-Party STT/TTS:** No references or imports of Deepgram, ElevenLabs, Sarvam, or Twilio.
- [ ] **No Audio in Backend:** Backend processes zero audio bytes; WebRTC flows strictly between client and Agora SDRTN.
- [ ] **Sub-500ms Conversational Latency:** From end of user speech to onset of Murf Falcon 2.1 audio playback.
- [ ] **Epistemic Classification Working:** User statements in Hindi/English are correctly segregated into Facts, Guesses, and Contradictions.
- [ ] **Barge-in Interruptibility:** Speaking while the agent is responding immediately silences the agent.
- [ ] **Actionable English Brief:** Session termination produces an executive-ready English ticket with verifiable action items.
