# VAD_LATENCY_TUNING.md — Acoustics, Barge-in & Latency Budget (Milestone 3)

Supersedes the 0.5 / 300 / 350 values in AGENTS.md §4.3. Source: `backend/agora_convo.ACOUSTIC_PROFILES`.

## Acoustic profiles (`POST /api/session/start {"environment": ...}`)
| Profile | speech_threshold | interrupt_ms | speaking_interrupt_ms | prefix_ms | silence_ms | client mic gain |
|---|---|---|---|---|---|---|
| `stage_noisy` (default) | 0.68 | 320 | 400 | 750 | 650 | 140% |
| `quiet` | 0.50 | 160 | 200 | 600 | 550 | 100% |
| `soft_voice` | 0.40 | 200 | 260 | 800 | 700 | 220% |

Mapped onto Agora's current schema: `turn_detection.config.{speech_threshold, start_of_speech.vad_config, end_of_speech.vad_config}`.

### Why these numbers
- **High threshold + long interrupt on stage**: PA bleed, crowd noise and the agent's own voice from laptop speakers must not trigger barge-in. `speaking_interrupt_duration_ms` is stricter than `interrupt_duration_ms` because echo only exists while the agent talks.
- **Soft voices** are caught by *amplifying the signal*, not by dropping the threshold into the noise floor: the browser mic runs AEC + ANS + AGC, and `client_mic_gain` (Agora `setVolume`, 100 = unity) lifts a quiet speaker above the VAD threshold. `soft_voice` also lowers the threshold and waits longer (700 ms) before ending a hesitant turn.
- **prefix_padding** 600-800 ms keeps soft Malayalam/Hinglish onsets ("Athe…", "Haan toh…") from being clipped.
- Semantic end-of-speech is unavailable for multi-language ARES (ml-IN,en-IN), so VAD silence is the end-of-turn signal; 550-650 ms balances hesitation vs. snappiness.

## Latency levers (user stops speaking → first Murf audio)
| Stage | Lever |
|---|---|
| Transport | `parameters.audio_scenario: "aiserver"` (Agora's latency + loss-resilience path), Opus speech_standard mic |
| End of turn | silence 550-650 ms (dominant cost — tune per room) |
| LLM | managed `gpt-4.1-mini`, `max_tokens 110`, `temperature 0.25`, `max_history 10` (smaller prompt → faster first token), system prompt: most important clause first, < 25 words, one question |
| Tools | triage/route run in < 1 ms server-side; Agora tool `timeout_ms 2500`; directive < 30 tokens so the LLM's second pass is short |
| TTS | Murf FALCON on India edge `in.api.murf.ai` (ap-south-1), 24 kHz streaming |

Measured live: RTM `message.metrics` (per-module asr/llm/tts ms) and `turn.finished.e2e_latency_ms` are shown in the UI pipeline strip.

## Barge-in
Enabled via `start_of_speech.mode = "vad"`. The UI logs `message.interrupt` events and marks interrupted agent bubbles.
