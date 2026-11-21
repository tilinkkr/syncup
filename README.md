# 🎙️ Multilingual Voice SyncUp

> **Track 2: Voice AI at Work: Beyond the Call Center**  
> Powered by **Agora Conversational AI Engine** + **Murf.ai Falcon 2.1 Streaming TTS**

---

## ⚡ Overview

**Multilingual Voice SyncUp** is an epistemic voice partner for frontline workers, site engineers, and shift supervisors. Unlike traditional call-center voice bots that handle scripted customer inquiries, SyncUp joins live daily operational standups, shift handovers, and safety debriefs.

Speaking natural, code-mixed **Indian Hindi / Hinglish and English**, the AI actively triages spoken updates in real time into **Facts**, **Guesses**, and **Contradictions** against company ground truth records, while generating an audit-ready **English Executive Ticket** for management and ERP dispatch.

---

## 🏗️ Architecture Highlights

* **Zero Audio in Backend:** WebRTC audio streams directly between worker devices and Agora SDRTN® edge cloud. The backend never ingests, proxies, or transcodes audio bytes.
* **Built-in Multilingual ASR (ARES):** Direct transcription of Indian code-mixed speech (`en-US,hi-IN`) with industrial vocabulary boosting.
* **Sub-100ms Murf.ai Falcon 2.1 TTS:** Agora's cloud directly streams synthesized 24kHz linear PCM audio over WebSockets from Murf's India edge server (`in.api.murf.ai`).
* **Sub-500ms End-to-End Latency:** Hardware VAD with 350ms silence detection and instant sub-80ms barge-in interruption.
* **Real-time Epistemic Triage:** Live 3-column triage board (Facts, Guesses, Debunked) synchronized across devices via **Agora RTM 2.x**.

---

## 📂 Architecture Contracts & Documentation

Every subsystem is strictly governed by modular specifications in [`/docs/`](file:///c:/Users/Tilin%20Bijoy/Desktop/Agorahacks/docs):

1. **[`AGENTS.md`](file:///c:/Users/Tilin%20Bijoy/Desktop/Agorahacks/AGENTS.md)** — Master Engineering & Architecture Contract.
2. **[`docs/AGORA_PIPELINE.md`](file:///c:/Users/Tilin%20Bijoy/Desktop/Agorahacks/docs/AGORA_PIPELINE.md)** — Token generation, Conversational AI REST `/join` & `/leave` endpoints, and RTM 2.x data streams.
3. **[`docs/MURF_TTS_CONFIG.md`](file:///c:/Users/Tilin%20Bijoy/Desktop/Agorahacks/docs/MURF_TTS_CONFIG.md)** — Falcon 2.1 WSS streaming, Indian voice IDs (`hi-IN-kabir`, `en-IN-eashan`), and Hinglish prosody.
4. **[`docs/VAD_LATENCY_TUNING.md`](file:///c:/Users/Tilin%20Bijoy/Desktop/Agorahacks/docs/VAD_LATENCY_TUNING.md)** — Sub-500ms latency budget, VAD tuning, and barge-in packet cancellation.
5. **[`docs/EPISTEMIC_ENGINE.md`](file:///c:/Users/Tilin%20Bijoy/Desktop/Agorahacks/docs/EPISTEMIC_ENGINE.md)** — Epistemic taxonomy, Ground Truth DB schemas, system prompt, and ticket generation.
6. **[`docs/UI_COMMAND_CENTER.md`](file:///c:/Users/Tilin%20Bijoy/Desktop/Agorahacks/docs/UI_COMMAND_CENTER.md)** — Next.js 14 Command Center, 60fps canvas visualizer, and live triage board.

---

## 🚀 Quickstart

### 1. Configure Credentials
```bash
cp .env.example .env
# Fill in your Agora and Murf.ai credentials in .env
```

### 2. Run Backend (FastAPI Python 3.11+)
```bash
cd backend
python -m venv venv
# On Windows:
.\venv\Scripts\activate
# On Linux/macOS:
source venv/bin/activate
pip install -r requirements.txt
uvicorn app.main:app --reload --port 8000
```

### 3. Run Frontend (Next.js 14+)
```bash
cd frontend
npm install
npm run dev
# Open http://localhost:3000 in your browser
```
