# LANGUAGE_PROSODY_TUNING.md — Per-language LLM, TTS & VAD calibration

> Source of truth: `backend/agora_convo.py` → `LANGUAGE_PROFILES`, `ACOUSTIC_PROFILES`, `compute_tuning()`.
> Verified by `backend/test_backend.py` §9 (every language × environment is asserted in the real `/join` payload).
> Stack: Agora Conversational AI Engine (ARES ASR + managed LLM + turn detection) → Murf Falcon 2.1 (`wss://in.api.murf.ai`).

## 1. Calibration matrix (base = `quiet` environment)

| Lang | ASR (ARES) | `llm.temperature` | `llm.presence_penalty` | Murf voice | `tts.rate` | `tts.pitch` | `tts.style` | `vad.threshold` | `interrupt_ms` | `prefix_ms` | `silence_ms` |
|---|---|---|---|---|---|---|---|---|---|---|---|
| **ml-IN** (default) | `ml-IN,en-IN` | **0.20** | 0.15 | `ml-IN-madhavan` | **−8** | −2 | Conversational | 0.55 | 180 | 700 | **680** |
| **kn-IN** | `kn-IN,en-IN` | **0.22** | 0.15 | `kn-IN-harshitha`* | **−5** | 0 | Conversational | 0.55 | 180 | 680 | **680** |
| **ta-IN** | `ta-IN,en-IN` | **0.22** | 0.15 | `ta-IN-karthikeyan`* | **−6** | −1 | Conversational | 0.55 | 180 | 680 | **660** |
| **hi-IN** (Hinglish) | `hi-IN,en-IN` | 0.35 | 0.25 | `ml-IN-madhavan` | 0 | 0 | Conversational | 0.53 | 170 | 600 | 580 |
| **en-IN** | `en-IN` | 0.30 | 0.20 | `en-IN-aarav` | **+3** | −1 | Conversational | 0.52 | 160 | 550 | 520 |

All: `max_tokens 110`, `sample_rate 24000`, `model falcon-2.1`, `max_history 10`.

\* The brief asked for `Madhavan` everywhere. A live `GET /v1/speech/voices?model=falcon-2.1` (Nov 2026) shows
`ml-IN-madhavan` supports only `ml-IN` and `hi-IN`, so `voice_preference` falls back to the native Kannada / Tamil
voice. `resolve_murf_voices()` re-checks this at every backend start and logs any switch.

## 2. Why the Dravidian languages are tuned differently

| Lever | ml / kn / ta | hi / en | Reason |
|---|---|---|---|
| **Temperature 0.20–0.22** vs 0.30–0.35 | lower | higher | The prompt carries strict output rules: native script for loanwords, phonetic codes (`ഇ സീറോ ഫോർ`), no `Line 3-ലെ` hyphen suffixes. Lower temperature keeps the model on those rules. Hinglish is supposed to be loose and code-mixed, so it gets more freedom. |
| **Presence penalty 0.15** vs 0.20–0.25 | lower | higher | Agglutinative languages legitimately repeat stems and case suffixes (`പാനൽ ബി-യിലെ`, `ಲೈನ್‌ನಲ್ಲಿ`). A high penalty pushes the model toward rarer, less natural word forms. |
| **TTS rate −5 to −8** vs 0 / +3 | slower | neutral/faster | Malayalam, Kannada and Tamil have long words and dense consonant clusters (`ക്ഷ`, `ന്ന`, `ಸ್ಕ`, `க்ஷ`). A slightly slower rate keeps each syllable intelligible on a factory floor. Indian English sounds most natural a little brisk (+3). |
| **Pitch −1 / −2** | slightly lower | 0 / −1 | Gives a calmer "senior maintenance lead" tone and keeps intonation steady when the speaker switches language mid-sentence. |
| **End-of-speech silence 660–680 ms** vs 580 / 520 ms | longer | shorter | These languages are verb-final (SOV), and workers pause while searching for a technical noun before the verb arrives. A 520 ms window would cut them off mid-thought. Hinglish and English turns end sooner and more predictably. |
| **Prefix padding 680–700 ms** | longer | 550–600 ms | Captures soft word-initial vowels and aspirates (`അ`, `ಆ`, `ஆ`) that would otherwise be clipped from the first word. |
| **VAD threshold 0.55** vs 0.52–0.53 | slightly stricter | looser | Leaves headroom for the slower, more patient window without false triggers from breathing during long pauses. |

## 3. Acoustic environment offsets (applied on top of the language base)

| Env | threshold | interrupt | speaking-interrupt | silence / prefix | Murf `volume_offset` | client mic gain |
|---|---|---|---|---|---|---|
| `stage_noisy` (default) | **+0.10**, capped at 0.72 | **+80 ms** | interrupt + 80 ms | ±0 / **−50 ms** | **−4** | 140 % |
| `quiet` | ±0 | ±0 | interrupt + 40 ms | ±0 | −4 | 100 % |
| `soft_voice` | −0.13, floor 0.38 | +20 ms | interrupt + 60 ms | +60 / +100 ms | −4 | 220 % |

**Echo protection on stage:** the PA speaker plays the agent's voice back into the worker's mic.
- A higher threshold and a longer barge-in window mean that bleed alone can't trigger a false self-interruption.
- `volume_offset: -4` lowers what reaches the PA.
- Measured live: a large offset (−20) lowered Murf's output RMS by about 4.5 dB, so the parameter does take effect.
- Example: ml-IN on stage → VAD 0.65, barge-in 260 ms (speaking 340 ms), prefix 650 ms, silence 680 ms.
- **Speaker lock (SAL):** every `/join` sets `advanced_features.enable_sal` + `sal.sal_mode: "locking"`, Agora's current
  replacement for the legacy `enable_aivad`/`enable_bhvs` flags. It locks onto the worker and blocks ~95% of other voices and noise.
  Interruption is the top-level `interruption: {enable: true, mode: "start_of_speech"}` (v2.6 schema).
- **Speaker Echo Guard (browser):** on laptop speakers, the mic is muted while the agent's track is audible and resumes
  250 ms after it goes quiet. Turn it off with headphones for full-duplex barge-in.
- **Zombie guard:** each call gets a fresh `syncup-<ms>` channel, and every agent the backend still tracks is stopped
  before a new `/join`. `POST /api/session/cleanup` stops them all.

Murf silently ignores voice-config keys it doesn't know. `style` must therefore be **`Conversational`**, the only style these Falcon voices list. `Conversation` is accepted without an error but does nothing.

## 4. Telemetry (visible to judges)

`POST /api/session/start` returns:
```json
"tuning": {"temperature": 0.2, "presence_penalty": 0.15, "voice": "ml-IN-madhavan", "style": "Conversational",
           "rate": -8, "pitch": -2, "volume_offset": -4, "vad_threshold": 0.65, "interrupt_ms": 260, "silence_ms": 680}
```
The same values are written to **LIVE PIPELINE LOGS** when the session starts:
```
[ASR] ARES ml-IN,en-IN | Stage / Noisy: VAD 0.65 / silence 680ms / barge-in 260ms (speaking 340ms) / prefix 650ms
[TTS] PROSODY ml-IN: LLM gpt-4.1-mini temp 0.20 presence 0.15 | Murf falcon-2.1 ml-IN-madhavan Conversational rate -8 pitch -2 vol -4 @24kHz
```
`GET /api/languages` exposes the effective tuning for every language × environment.

## 5. Spoken codes & confirmation lines

- **Code spelling.** `phonetics.py` spells codes in native script for ml, kn and ta: `E-04` → `ഇ സീറോ ഫോർ` / `ಇ ಜೀರೋ ಫೋರ್` / `இ ஜீரோ ஃபோர்`. For hi and en, hyphens become spaces (`SYNC 104`). The UI always shows the exact code.
- **Fixed confirmation sentences.** The approval question and the routed confirmation are fixed templates in each language (`speech.confirm` / `speech.routed`). Every one is under Agora's 512-byte `/speak` limit, the largest being Tamil routed at 317 B. The supervisor's Approve button can therefore have the live agent say the confirmation aloud.

## 6. How to re-tune

1. Edit the profile in `LANGUAGE_PROFILES` (`llm_params`, `tts_params`, `vad_base`).
2. Listen to it: `backend\.venv\Scripts\python.exe backend\test_malayalam_audio.py "<sentence>" stage_noisy`.
3. Update the `WANT` table in `test_backend.py` §9 and run the suite.
