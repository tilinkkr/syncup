# UI_COMMAND_CENTER.md — Frontend Command Center Architecture & Design Specification

> **Scope:** Architecture, component specifications, state management, Agora WebRTC/RTM integration hooks, and audio visualizer mechanics for the Next.js Command Center.

---

## 1. UI Philosophy & Visual Design System

The **Multilingual Voice SyncUp Command Center** is engineered for high-visibility industrial, construction, and enterprise environments. It provides real-time situational awareness during voice standups.

* **Design Aesthetic:** Deep Slate / Obsidian Dark Mode (`#0a0f1d`), tactical cyber-industrial typography, vibrant epistemic status accents.
* **Epistemic Color Scheme:**
  * **Verified Facts:** Emerald Green (`#10b981`, `bg-emerald-950/40`, `border-emerald-500/40`)
  * **Unverified Guesses:** Amber Yellow (`#f59e0b`, `bg-amber-950/40`, `border-amber-500/40`)
  * **Contradictions / Debunked:** Crimson Rose (`#f43f5e`, `bg-rose-950/40`, `border-rose-500/40`)
  * **System & Audio Telemetry:** Cyan / Electric Blue (`#06b6d4`, `bg-cyan-950/40`, `border-cyan-500/40`)

---

## 2. Command Center Layout Wireframe

```text
┌─────────────────────────────────────────────────────────────────────────────┐
│ [●] SYNCUP COMMAND CENTER  |  Channel: syncup-room-101  |  TTFA: 94ms       │
│ Status: [ LIVE ]  |  Voice: Murf Falcon 2.1 (Kabir)  |  [ MIC ON ] [ LEAVE ] │
├─────────────────────────────────────────────────────────────────────────────┤
│ ┌────────────────────────────────────┐ ┌──────────────────────────────────┐ │
│ │  LIVE AUDIO SPECTRUM (60fps Canvas)│ │  AGENT ORB / CONVERSATIONAL STATE│ │
│ │  Worker Mic: ▅▆▇▃▂   Agent: ▂▃▅▆▇█ │ │  State: [ SPEAKING (Hinglish) ]  │ │
│ └────────────────────────────────────┘ └──────────────────────────────────┘ │
├─────────────────────────────────────────────────────────────────────────────┤
│ ┌──────────────────────────────────┐ ┌────────────────────────────────────┐ │
│ │ LIVE BILINGUAL TRANSCRIPT FEED   │ │ EPISTEMIC TRIAGE BOARD (3-Column)  │ │
│ │ [08:31] Worker: Subah se boiler  │ │ ┌──────────┐┌──────────┐┌──────────┐│ │
│ │ 2 ka pressure fluctuating lag    │ │ │ FACTS    ││ GUESSES  ││ DEBUNKED ││ │
│ │ raha hai, valve loose hai kya?   │ │ │ (Green)  ││ (Amber)  ││ (Rose)   ││ │
│ │                                  │ │ └──────────┘└──────────┘└──────────┘│ │
│ │ [08:31] SyncUp AI: Sensor        │ │ • Boiler 2  • Valve     • Line 2   │ │
│ │ telemetry 4.1 bar normal dikha   │ │   reading     leak        running  │ │
│ │ raha hai. Kya leak check kiya?   │ │   4.1 bar     unverified  REFUTED  │ │
│ └──────────────────────────────────┘ └────────────────────────────────────┘ │
├─────────────────────────────────────────────────────────────────────────────┤
│ 📋 LIVE EXECUTIVE BRIEF & ACTION ROUTER (Auto-compiled English Ticket)       │
│ Title: Shift A Standup - Boiler 2 Diagnostics & Line 2 LOTO                 │
│ Action Items: [1] Manual leak probe (Rajesh) | [2] LOTO Audit (Arun)        │
│ [ EXPORT TO JIRA ]  [ COPY MARKDOWN ]  [ SYNC TO SUPABASE ]                 │
└─────────────────────────────────────────────────────────────────────────────┘
```

---

## 3. Component Hierarchy & Responsibilities

```text
src/app/page.tsx (Main Command Center Hub)
  ├── components/ControlBar.tsx
  │     ├── Channel input & session connect button
  │     ├── Mic mute/unmute toggle
  │     ├── Agent status indicator (IDLE, CONNECTING, LISTENING, SPEAKING)
  │     └── TTFA & RTT latency badge
  │
  ├── components/AudioVisualizer.tsx
  │     ├── Dual Web Audio API AnalyserNode hooks (Mic Track & Agent Remote Track)
  │     └── High-performance Canvas 2D spectrum renderer (60 FPS)
  │
  ├── components/TranscriptFeed.tsx
  │     ├── Auto-scrolling bilingual utterance list
  │     ├── Speaker badges (`Worker` vs `SyncUp AI`)
  │     └── Language detection tag badges (`[HI]`, `[EN]`, `[HINGLISH]`)
  │
  ├── components/TriageBoard.tsx
  │     ├── Column 1: Facts (Verified ground truth statements with confidence score)
  │     ├── Column 2: Guesses (Unverified assertions with "Mark Verified" CTA)
  │     └── Column 3: Debunked (Refuted statements with DB conflict justification)
  │
  └── components/ExecutiveTicket.tsx
        ├── English executive summary card
        ├── Severity rating badge (`CRITICAL`, `HIGH`, `MEDIUM`, `LOW`)
        ├── Concrete Action Items table (Task, Owner, Deadline, Priority)
        └── Export action buttons (Clipboard, JSON, Supabase/Webhook push)
```

---

## 4. Agora React Hooks Specifications

### 4.1 `useAgoraRTC` Hook (`src/hooks/useAgoraRTC.ts`)
Encapsulates WebRTC client initialization, microphone capture, publishing, remote agent track subscription, and Web Audio API analyser binding.

```typescript
export interface UseAgoraRTCOptions {
  appId: string;
  channel: string;
  rtcToken: string;
  uid: number;
}

export function useAgoraRTC() {
  // Returns:
  // - client: IAgoraRTCClient
  // - localAudioTrack: IMicrophoneAudioTrack | null
  // - remoteAudioTrack: IRemoteAudioTrack | null
  // - isJoined: boolean
  // - isMuted: boolean
  // - agentState: 'idle' | 'listening' | 'speaking'
  // - joinChannel: (options: UseAgoraRTCOptions) => Promise<void>
  // - leaveChannel: () => Promise<void>
  // - toggleMic: () => void
  // - getMicAnalyser: () => AnalyserNode | null
  // - getAgentAnalyser: () => AnalyserNode | null
}
```

### 4.2 `useAgoraRTM` Hook (`src/hooks/useAgoraRTM.ts`)
Encapsulates Agora RTM 2.x client login, channel topic subscription, and event dispatching to React state.

```typescript
export interface TranscriptItem {
  id: string;
  speaker: "worker" | "agent";
  text: string;
  language: string;
  timestamp: number;
}

export interface TriageItem {
  id: string;
  statement: string;
  category: "fact" | "guess" | "contradiction";
  confidence: number;
  db_checked: boolean;
  db_status?: string;
  clarification_prompt?: string;
}

export interface ExecutiveTicketData {
  ticket_id: string;
  title: string;
  severity: string;
  facts: string[];
  unresolved_guesses: string[];
  contradictions_resolved: string[];
  action_items: Array<{
    task: string;
    owner: string;
    priority: "low" | "medium" | "high" | "critical";
    deadline?: string;
  }>;
}

export function useAgoraRTM() {
  // Returns:
  // - transcripts: TranscriptItem[]
  // - triageItems: TriageItem[]
  // - currentTicket: ExecutiveTicketData | null
  // - subscribeChannel: (appId: string, channel: string, rtmToken: string, userId: string) => Promise<void>
  // - unsubscribeChannel: () => Promise<void>
}
```

---

## 5. Web Audio API Canvas Visualizer Implementation Details

To achieve high-efficiency 60fps rendering without React re-render lag:
1. `AudioContext` connects to `MediaStreamAudioSourceNode` generated from `localAudioTrack.getMediaStreamTrack()` and `remoteAudioTrack.getMediaStreamTrack()`.
2. `AnalyserNode` configured with:
   * `fftSize: 64` (produces 32 frequency bins).
   * `smoothingTimeConstant: 0.8` (creates fluid organic wave movement).
3. `requestAnimationFrame` loop draws directly to an HTML5 `<canvas>` element without triggering React component re-renders.

---

## 6. Real-Time Telemetry & Latency Display

The Control Bar displays live connection diagnostics:
* **Connection State:** WebRTC connected status via `client.connectionState`.
* **Audio Round-Trip Time (RTT):** Polled via `client.getRTCStats().RTT`.
* **Time-to-First-Audio (TTFA):** Measured from end of worker speech event (VAD silence trigger) to first audio packet timestamp from Murf Falcon 2.1.
