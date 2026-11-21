# AGORA_PIPELINE.md — Agora ConvoAI Lifecycle Contract (Milestone 2, verified live Nov 2026)

Source of truth: https://docs.agora.io/llms/doc-versions-convoai-api-v1.txt (join / leave reference) and
https://docs.agora.io/en/ai/build/managed-mode.md, /tools/custom-tools.md, /models/asr/ares.md, /models/tts/murf.md.

## Credentials (backend/.env)
| Var | Use | Status |
|---|---|---|
| `AGORA_APP_ID` | project id (`91ecc776…`, discovered via `GET /dev/v1/projects`) | set |
| `AGORA_APP_CERTIFICATE` | signs RTC/RTM tokens. **Project has a certificate enabled** — an empty token makes the agent exit with "RTC connection error" | REQUIRED, missing |
| `AGORA_CUSTOMER_ID` / `_SECRET` | REST Basic Auth | verified |

## /join (POST .../v2/projects/{appid}/join)
```json
{ "name": "syncup-<channel>-<ts>",
  "properties": {
    "channel": "<channel>", "token": "<agent RTC token, uid 0>",
    "agent_rtc_uid": "0", "remote_rtc_uids": ["1001"], "enable_string_uid": false, "idle_timeout": 120,
    "advanced_features": {"enable_tools": true},
    "asr": {"vendor": "ares", "language": "ml-IN,en-IN", "keywords": ["SyncUp","gearbox","thermal relay","E-04", "..."]},
    "turn_detection": {"mode": "default", "config": {
        "speech_threshold": 0.55,
        "start_of_speech": {"mode": "vad", "vad_config": {"interrupt_duration_ms": 180, "speaking_interrupt_duration_ms": 180, "prefix_padding_ms": 600}},
        "end_of_speech":   {"mode": "vad", "vad_config": {"silence_duration_ms": 550}}}},
    "llm": {"credential_mode": "managed", "vendor": "openai", "style": "openai",
            "url": "https://api.openai.com/v1/chat/completions",
            "params": {"model": "gpt-4.1-mini", "max_tokens": 110, "temperature": 0.25},
            "system_messages": [...], "greeting_message": "<per language>", "failure_message": "<per language>",
            "max_history": 16, "template_variables": {"webhook_secret": "<WEBHOOK_SECRET>"},
            "tools": [ "see Tools" ]},
    "tts": {"vendor": "murf", "params": "see MURF_TTS_CONFIG.md"} } }
```
- `credential_mode: "managed"` = Agora-hosted LLM, no OpenAI key (models: gpt-4o-mini, gpt-4.1-mini, gpt-5-nano, gpt-5-mini). Set `LLM_CREDENTIAL_MODE=byok` + `LLM_API_KEY` to bring your own.
- Old flat `turn_detection.agora_vad_config` is deprecated (MLLM-only) — do not use.
- Semantic end-of-speech only works for single en-US/en-IN; multi-language ARES falls back to VAD (what we use).

## Tools (Agora custom HTTPS tools)
Each `llm.tools[]` entry = `{type:"function", function:{name, description, parameters}, execution:{mode:"sync"}, server:{method:"POST", url, headers, body, timeout_ms}}`.
- `url` must be public HTTPS — `localhost` is rejected (`InvalidFieldValue … host "localhost" is blocked`). Use ngrok.
- Body values must be whole placeholders (`"{{args.asset_id}}"`); all params are `required` so no placeholder is ever missing.
- Auth: header `X-SyncUp-Key: {{template_variables.webhook_secret}}`, verified by FastAPI.
- Engine makes one sync call and feeds the JSON response (`directive`) back to the LLM.

## /leave
`POST .../v2/projects/{appid}/agents/{agent_id}/leave`. Status: `GET .../agents/{agent_id}` (returns `status` + failure `message`).

## Languages (backend/agora_convo.LANGUAGE_PROFILES)
| Code | ARES `language` | Murf voice / locale |
|---|---|---|
| ml-IN (default) | ml-IN,en-IN | ml-IN-nimisha / ml-IN |
| hi-IN | en-IN,hi-IN | en-IN-aarav / hi-IN |
| kn-IN | kn-IN,en-IN | kn-IN-harshitha / kn-IN |
| ta-IN | ta-IN,en-IN | ta-IN-karthikeyan / ta-IN |
| en-IN | en-IN | en-IN-aarav / en-IN |
ARES lists ml-IN as a supported language (docs: realtime STT supported-languages), so Malayalam is recognised natively.

## Milestone 3 additions
- **RTM transcripts**: `advanced_features.enable_rtm: true` + `parameters: {data_channel: "rtm", enable_metrics: true, enable_error_message: true, audio_scenario: "aiserver"}`.
  Browser logs into RTM as `"1001"`, subscribes to the channel (`withMessage`, `withPresence`) and parses JSON messages:
  `user.transcription` (`text`, `final`, `turn_id`), `assistant.transcription` (`text`, `turn_status` 0 in-progress / 1 end / 2 interrupted),
  `message.interrupt`, `message.metrics` (`module` asr|llm|tts, `latency_ms`), `turn.finished` (`payload.metrics.e2e_latency_ms`).
  Agent state (listening/thinking/speaking) arrives as RTM presence `stateChanged.state`. Fallback: RTC `stream-message`, chunked `id|idx|sum|base64`.
- **Tokens**: with RTM enabled the agent token must carry RTC **and** RTM privileges → AccessToken2 (`007`) built by `backend/agora_token2.py`
  (port of Agora's official AccessToken2 / `build_token_with_rtm`). Agent uid is fixed at `999999`; the user's single 007 token serves RTC join + RTM login.
- **Signaling must be enabled** for the Agora project (Console → project → Signaling/RTM) or RTM login fails (UI falls back gracefully, captions off).
- `GET /api/preflight` (< 1.5 s, concurrent + time-boxed): `agora_creds`, `agora_rest`, `murf_api`, `webhook_tunnel` (round-trips through the public URL to `/health`).
- `POST /api/session/{channel}/simulate?pace=1.2` — scripted Malayalam LINE-03 run through the real `run_triage` / `run_route`; stage fallback when Wi-Fi blocks WebRTC UDP.
