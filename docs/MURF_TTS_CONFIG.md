# MURF_TTS_CONFIG.md — Murf Falcon Streaming TTS Contract (verified live Nov 2026)

Agora-validated `tts` block (docs.agora.io/en/ai/models/tts/murf.md):
```json
"tts": {"vendor": "murf", "params": {
  "api_key": "$MURF_API_KEY", "base_url": "wss://in.api.murf.ai/v1/speech/stream-input",
  "voiceId": "ml-IN-nimisha", "locale": "ml-IN", "model": "FALCON",
  "rate": 0, "pitch": 0, "sample_rate": 24000}}
```
- `model` is `FALCON` in the stream API; `falcon-2.1` is only the voice-catalogue filter (`GET /v1/speech/voices?model=falcon-2.1`).
- India edge `in.api.murf.ai` verified (region ap-south-1). Account concurrency limit: **3 streams**.
- Voices are validated at backend startup (`resolve_murf_voices`); an invalid voice/locale pair is auto-replaced by a native voice for that locale that also speaks en-IN.
- `en-IN-anisha` does NOT support ml-IN or kn-IN — do not use it for those languages.

## Latency rules
1. Spoken output < 25 words per turn (system prompt + `max_tokens: 110`).
2. One question per turn; no lists/markdown/emojis.
3. Murf key lives only in backend/.env and the server-side /join payload. Never sent to the browser.
