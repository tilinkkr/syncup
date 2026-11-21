export const BACKEND_URL = (process.env.NEXT_PUBLIC_BACKEND_URL || "http://localhost:8000").replace(/\/$/, "");
export const CHANNEL_NAME = process.env.NEXT_PUBLIC_CHANNEL_NAME || "syncup-floor-01";

export interface LanguageOption {
  code: string;
  label: string; // full label incl. native script
  short: string; // used in CTA copy: "Start Malayalam Voice Intake"
  tag: string;
}

// Mirrors backend agora_convo.LANGUAGE_PROFILES (ml-IN is the default worker language).
export const LANGUAGES: LanguageOption[] = [
  { code: "ml-IN", label: "Malayalam (മലയാളം)", short: "Malayalam", tag: "ML" },
  { code: "hi-IN", label: "Hinglish (हिन्दी)", short: "Hinglish", tag: "HI" },
  { code: "kn-IN", label: "Kannada (ಕನ್ನಡ)", short: "Kannada", tag: "KN" },
  { code: "ta-IN", label: "Tamil (தமிழ்)", short: "Tamil", tag: "TA" },
  { code: "en-IN", label: "English (India)", short: "English", tag: "EN" },
];

export interface ScenarioOption {
  id: string;
  label: string;
  detail: string;
}

export const SCENARIOS: ScenarioOption[] = [
  { id: "LINE-03", label: "LINE-03", detail: "Packaging Line" },
  { id: "GATE-02", label: "GATE-02", detail: "Dispatch Scanner" },
];

export const languageByCode = (code: string) => LANGUAGES.find((l) => l.code === code) ?? LANGUAGES[0];

export interface AcousticOption {
  id: "stage_noisy" | "quiet" | "soft_voice";
  label: string;
  hint: string;
}

// Mirrors backend agora_convo.ACOUSTIC_PROFILES: offsets on top of each language's calibrated VAD base
// (docs/LANGUAGE_PROSODY_TUNING.md). stage_noisy is the default for live demos.
export const ACOUSTICS: AcousticOption[] = [
  { id: "stage_noisy", label: "Stage / Noisy", hint: "VAD +0.13 · barge-in +140ms · Murf vol -4 · rejects PA bleed & echo" },
  { id: "quiet", label: "Quiet Room", hint: "Language-calibrated base VAD · snappiest turn-taking" },
  { id: "soft_voice", label: "Soft Voice", hint: "VAD -0.13 · +120% mic gain · catches quiet, distant speakers" },
];
