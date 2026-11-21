"""Agora Conversational AI Engine controller: /join, /leave and /speak with ARES ASR + Agora-managed LLM + Murf Falcon.

Schema verified against docs.agora.io (Nov 2026):
  - turn_detection.config.{speech_threshold, start_of_speech.vad_config, end_of_speech.vad_config}
  - llm.credential_mode = "managed" (Agora-hosted OpenAI model, no key) or "byok"
  - llm.tools[] = {type, function, execution, server{method,url,headers,body}} + advanced_features.enable_tools
  - tts murf params: api_key, base_url, voiceId, locale, model, rate, pitch, style, volume_offset, sample_rate
  - POST /agents/{id}/speak {text <= 512 bytes, priority, interruptable}
Per-language prosody / LLM / VAD calibration: docs/LANGUAGE_PROSODY_TUNING.md.
"""
import base64
import logging
import time
from urllib.parse import quote

import httpx

import settings
import speech_normalizer

log = logging.getLogger("syncup.agora")

AGORA_API_BASE = "https://api.agora.io/api/conversational-ai-agent/v2/projects"
MURF_STYLE = "Conversational"  # the only style Murf lists for these Falcon voices ("Conversation" is silently ignored)

# Industrial vocabulary ARES must not mangle, plus Manglish/Hinglish phonetic forms workers actually say.
BASE_KEYWORDS = ["SyncUp", "Line 3", "Gate 2", "gearbox", "thermal relay", "E-04", "Panel B",
                 "scanner", "server", "PoE", "VFD", "LED", "Bosch", "dispatch"]

# Voices: `voice_preference` is tried in order against GET /v1/speech/voices?model=falcon-2.1 at startup
# (resolve_murf_voices). Checked live Nov 2026: ml-IN-madhavan supports ml-IN + hi-IN only, so kn-IN and ta-IN
# fall back to their native voices. tts_params.voiceId holds the statically verified choice.
#
# Calibration rationale (see docs/LANGUAGE_PROSODY_TUNING.md):
#   Dravidian languages (ml/kn/ta) are agglutinative: long words, dense consonant clusters, verb-final clauses and
#   long hesitation pauses mid-turn -> lower temperature (strict script/phonetic rules), slower TTS rate and a
#   longer end-of-speech window (660-680 ms). Hinglish/English are faster-paced with shorter pauses.
LANGUAGE_PROFILES: dict[str, dict] = {
    "ml-IN": {
        "label": "Malayalam (മലയാളം)",
        "short": "Malayalam",
        # ARES recognises Malayalam natively; en-IN stays as the secondary language for code-mixed technical terms.
        "asr_language": "ml-IN,en-IN",
        "llm_params": {"temperature": 0.20, "presence_penalty": 0.15, "max_tokens": 110},
        "voice_preference": ["ml-IN-madhavan", "ml-IN-nimisha"],
        "tts_params": {"voiceId": "ml-IN-madhavan", "locale": "ml-IN", "style": MURF_STYLE, "rate": -8,
                       "pitch": -2, "sample_rate": 24000, "model": "falcon-2.1"},
        "vad_base": {"threshold": 0.55, "interrupt_duration_ms": 180, "prefix_padding_ms": 700,
                     "silence_duration_ms": 680},
        "speak_codes_phonetically": True,  # tool responses carry Malayalam spellings of codes (see phonetics.py)
        "keywords": ["പ്രശ്നം", "ചുവപ്പ്", "നിന്നു", "ഗിയർബോക്സ്", "തെർമൽ റിലേ", "പാനൽ", "സ്കാനർ", "സെർവർ",
                     "prashnam", "chuvappu", "panel"],
        "greeting": "നമസ്കാരം! സിങ്ക് അപ്പ് ആണ് സംസാരിക്കുന്നത്. ഫ്ലോറിൽ എന്താണ് പ്രശ്നം എന്ന് പറയാമോ?",
        "failure": "ക്ഷമിക്കണം, ഒന്നുകൂടി പറയാമോ?",
        "prompt_lang_instruction": (
            "Reply ONLY in natural spoken Malayalam (സംസാരഭാഷ). Your text goes straight to a Malayalam TTS voice, "
            "so format every reply for clean pronunciation:\n"
            "  a) Write ALL words in Malayalam Unicode script (മലയാളം), never Roman/Manglish — including technical "
            "loanwords: ഗിയർബോക്സ് (gearbox), തെർമൽ റിലേ (thermal relay), സ്കാനർ (scanner), സെർവർ (server), "
            "ടിക്കറ്റ് (ticket), പാനൽ ബി (Panel B), ലൈൻ ത്രീ (Line 3), ലൈറ്റ് (LED light).\n"
            "  b) NEVER attach a Malayalam suffix to English letters or digits with a hyphen. Wrong: 'Line 3-ലെ', "
            "'Panel B-യിലെ'. Right: 'ലൈൻ ത്രീയിലെ', 'പാനൽ ബി-യിലെ'.\n"
            "  c) Talk about codes like a person, never like a machine. Never read record or part IDs (LOG-891, "
            "TR-882) — say 'ആറു ദിവസം മുമ്പത്തെ മെയിന്റനൻസ് റെക്കോർഡ്', 'ഒരു പുതിയ തെർമൽ റിലേ'. Say an error code "
            "at most once, naturally: 'ഇ സീറോ ഫോർ എറർ' (never 'E-04', never 'minus'). Say a ticket only as "
            "'ടിക്കറ്റ് നമ്പർ വൺ സീറോ ഫോർ' — never the SYNC prefix. Tool results give you these spoken forms.\n"
            "  d) Use natural conversational markers with a comma after them (ശരി, മനസ്സിലായി, പക്ഷേ,).\n"
            "  e) Every reply 1 to 2 short sentences, maximum 15 words, plain text only."
        ),
        "example": "Worker: 'ലൈൻ ത്രീ നിന്നു, ഗിയർബോക്സ് പോയി എന്ന് തോന്നുന്നു.' You: 'ശരി, മനസ്സിലായി. പക്ഷേ, "
                   "ഗിയർബോക്സ് ആറു ദിവസം മുമ്പ് മാറ്റിയതാണ്. പാനൽ ബി-യിലെ തെർമൽ റിലേ ലൈറ്റ് ചുവപ്പാണോ?'",
        "speech": {
            "confirm": "ശരി, മനസ്സിലായി. ടിക്കറ്റ് നമ്പർ {ticket} ക്രിയേറ്റ് ചെയ്ത് {part} റിസർവ് ചെയ്യട്ടെ?",
            "routed": "നന്ദി. ടിക്കറ്റ് നമ്പർ {ticket} ഉണ്ടാക്കി. ഞാൻ ഇപ്പോൾ തന്നെ എഞ്ചിനീയറെ വിളിച്ച് അറിയിക്കാം. മുപ്പത് മിനിറ്റിൽ വീണ്ടും വിളിക്കാം.",
            "eta": "എഞ്ചിനീയർ {eta} മിനിറ്റിനുള്ളിൽ എത്തും. അതുവരെ ലൈൻ ഓഫ് ആയി തന്നെ വെക്കണേ.",
            "yes_words": ["അതെ", "ചെയ്യൂ", "ശരി", "ഓക്കെ", "Yes"],
        },
    },
    "hi-IN": {
        "label": "Hinglish (हिन्दी)",
        "short": "Hinglish",
        "asr_language": "hi-IN,en-IN",
        "llm_params": {"temperature": 0.35, "presence_penalty": 0.25, "max_tokens": 110},
        "voice_preference": ["ml-IN-madhavan", "en-IN-aarav"],
        "tts_params": {"voiceId": "ml-IN-madhavan", "locale": "hi-IN", "style": MURF_STYLE, "rate": 0,
                       "pitch": 0, "sample_rate": 24000, "model": "falcon-2.1"},
        "vad_base": {"threshold": 0.53, "interrupt_duration_ms": 170, "prefix_padding_ms": 600,
                     "silence_duration_ms": 580},
        "speak_codes_phonetically": False,  # hi-IN voices read "SYNC 104" / "E 04" cleanly in Latin script
        "keywords": ["band ho gaya", "kharab", "laal", "batti", "बंद", "खराब", "लाल"],
        "greeting": "नमस्ते! सिंक अप बोल रहा हूँ। फ्लोर पर क्या दिक्कत आ रही है, बताइए?",
        "failure": "माफ़ कीजिए, एक बार फिर बोलिए?",
        "prompt_lang_instruction": (
            "Speak warm, natural workplace Hinglish: Hindi in Devanagari script, with clean English technical nouns "
            "kept in Latin script (gearbox, thermal relay, Line 3, Panel B). Never read record or part IDs aloud; say an "
            "error code once, naturally ('E zero four error'), and a ticket only as 'टिकट नंबर one zero four'. Use natural transitions like 'अच्छा, समझ गया,' and "
            "'एक बार चेक करके बताइए'. Every reply 1 to 2 short sentences, maximum 15 words, plain text only."
        ),
        "example": "Worker: 'Line 3 बंद है, gearbox जल गया लगता है।' You: 'अच्छा, समझ गया। पर gearbox छह दिन पहले "
                   "बदला था। Panel B पर thermal relay की LED लाल है? एक बार चेक करके बताइए।'",
        "speech": {
            "confirm": "अच्छा, समझ गया। टिकट नंबर {ticket} बनाकर {part} रिज़र्व कर दूँ?",
            "routed": "धन्यवाद। टिकट नंबर {ticket} बन गया। मैं अभी engineer को call करके बता देता हूँ। तीस मिनट में फिर से call करूँगा।",
            "eta": "Engineer {eta} मिनट में पहुँच रहे हैं। तब तक line बंद ही रखिए।",
            "yes_words": ["हाँ", "कर दो", "ठीक है", "Yes"],
        },
    },
    "kn-IN": {
        "label": "Kannada (ಕನ್ನಡ)",
        "short": "Kannada",
        "asr_language": "kn-IN,en-IN",
        "llm_params": {"temperature": 0.22, "presence_penalty": 0.15, "max_tokens": 110},
        "voice_preference": ["ml-IN-madhavan", "kn-IN-harshitha"],
        "tts_params": {"voiceId": "kn-IN-harshitha", "locale": "kn-IN", "style": MURF_STYLE, "rate": -5,
                       "pitch": 0, "sample_rate": 24000, "model": "falcon-2.1"},
        "vad_base": {"threshold": 0.55, "interrupt_duration_ms": 180, "prefix_padding_ms": 680,
                     "silence_duration_ms": 680},
        "speak_codes_phonetically": True,
        "keywords": ["ಸಮಸ್ಯೆ", "ನಿಂತಿದೆ", "ಕೆಂಪು", "ಗೇರ್‌ಬಾಕ್ಸ್", "ಥರ್ಮಲ್ ರಿಲೇ", "samasye", "nintide", "kempu"],
        "greeting": "ನಮಸ್ಕಾರ! ಸಿಂಕ್ ಅಪ್ ಮಾತಾಡ್ತಿದ್ದೀನಿ. ಫ್ಲೋರ್‌ನಲ್ಲಿ ಏನು ಸಮಸ್ಯೆ ಆಗಿದೆ ಅಂತ ಹೇಳ್ತೀರಾ?",
        "failure": "ಕ್ಷಮಿಸಿ, ಇನ್ನೊಂದು ಸಲ ಹೇಳ್ತೀರಾ?",
        "prompt_lang_instruction": (
            "Reply ONLY in natural colloquial Bengaluru Kannada, written in Kannada Unicode script (ಕನ್ನಡ), never "
            "Roman script. Your text goes straight to a Kannada TTS voice:\n"
            "  a) Write technical loanwords in Kannada script too: ಗೇರ್‌ಬಾಕ್ಸ್ (gearbox), ಥರ್ಮಲ್ ರಿಲೇ (thermal relay), "
            "ಲೈನ್ ತ್ರೀ (Line 3), ಪ್ಯಾನಲ್ ಬಿ (Panel B), ಟಿಕೆಟ್ (ticket).\n"
            "  b) Talk about codes like a person: never read record or part IDs (LOG-891, TR-882); say an error "
            "code at most once as 'ಇ ಜೀರೋ ಫೋರ್ ಎರರ್'; say a ticket only as 'ಟಿಕೆಟ್ ನಂಬರ್ ಒನ್ ಜೀರೋ ಫೋರ್'. "
            "Tool results give you these spoken forms.\n"
            "  c) Use polite conversational phrasing: 'ಸರಿ, ಗೊತ್ತಾಯ್ತು,' and 'ಒಮ್ಮೆ ಚೆಕ್ ಮಾಡ್ತೀರಾ?'.\n"
            "  d) Every reply 1 to 2 short sentences, maximum 15 words, plain text only."
        ),
        "example": "Worker: 'ಲೈನ್ ತ್ರೀ ನಿಂತಿದೆ, ಗೇರ್‌ಬಾಕ್ಸ್ ಹೋಗಿದೆ ಅನ್ಸುತ್ತೆ.' You: 'ಸರಿ, ಗೊತ್ತಾಯ್ತು. ಆದರೆ ಗೇರ್‌ಬಾಕ್ಸ್ "
                   "ಆರು ದಿನದ ಹಿಂದೆ ಬದಲಾಯಿಸಿದ್ದು. ಪ್ಯಾನಲ್ ಬಿ ಥರ್ಮಲ್ ರಿಲೇ ಲೈಟ್ ಕೆಂಪಾಗಿದೆಯಾ, ಒಮ್ಮೆ ಚೆಕ್ ಮಾಡ್ತೀರಾ?'",
        "speech": {
            "confirm": "ಸರಿ, ಗೊತ್ತಾಯ್ತು. ಟಿಕೆಟ್ ನಂಬರ್ {ticket} ಕ್ರಿಯೇಟ್ ಮಾಡಿ {part} ರಿಸರ್ವ್ ಮಾಡ್ಲಾ?",
            "routed": "ಧನ್ಯವಾದ. ಟಿಕೆಟ್ ನಂಬರ್ {ticket} ಆಯ್ತು. ನಾನು ಈಗಲೇ ಎಂಜಿನಿಯರ್‌ಗೆ ಕಾಲ್ ಮಾಡಿ ತಿಳಿಸ್ತೀನಿ. ಮೂವತ್ತು ನಿಮಿಷದಲ್ಲಿ ಮತ್ತೆ ಕಾಲ್ ಮಾಡ್ತೀನಿ.",
            "eta": "ಎಂಜಿನಿಯರ್ {eta} ನಿಮಿಷದಲ್ಲಿ ಬರ್ತಾರೆ. ಅಲ್ಲಿವರೆಗೂ ಲೈನ್ ಆಫ್ ಆಗೇ ಇರಲಿ.",
            "yes_words": ["ಹೌದು", "ಮಾಡಿ", "ಸರಿ", "Yes"],
        },
    },
    "ta-IN": {
        "label": "Tamil (தமிழ்)",
        "short": "Tamil",
        "asr_language": "ta-IN,en-IN",
        "llm_params": {"temperature": 0.22, "presence_penalty": 0.15, "max_tokens": 110},
        "voice_preference": ["ml-IN-madhavan", "ta-IN-karthikeyan"],
        "tts_params": {"voiceId": "ta-IN-karthikeyan", "locale": "ta-IN", "style": MURF_STYLE, "rate": -6,
                       "pitch": -1, "sample_rate": 24000, "model": "falcon-2.1"},
        "vad_base": {"threshold": 0.55, "interrupt_duration_ms": 180, "prefix_padding_ms": 680,
                     "silence_duration_ms": 660},
        "speak_codes_phonetically": True,
        "keywords": ["பிரச்சனை", "நின்னுடுச்சு", "சிவப்பு", "prachinai", "ninnuduchu", "sivappu"],
        "greeting": "வணக்கம்! சிங்க் அப் பேசுகிறேன். ஃப்ளோரில் என்ன பிரச்சனை என்று சொல்லுங்கள்?",
        "failure": "மன்னிக்கவும், இன்னொரு முறை சொல்லுங்கள்?",
        "prompt_lang_instruction": (
            "Reply ONLY in natural conversational Tamil, written in Tamil Unicode script (தமிழ்), never Roman "
            "script. Your text goes straight to a Tamil TTS voice:\n"
            "  a) Write technical loanwords in Tamil script too: கியர்பாக்ஸ் (gearbox), தெர்மல் ரிலே (thermal relay), "
            "லைன் த்ரீ (Line 3), பேனல் பி (Panel B), டிக்கெட் (ticket).\n"
            "  b) Talk about codes like a person: never read record or part IDs (LOG-891, TR-882); say an error "
            "code at most once as 'இ ஜீரோ ஃபோர் எரர்'; say a ticket only as 'டிக்கெட் நம்பர் ஒன் ஜீரோ ஃபோர்'. "
            "Tool results give you these spoken forms.\n"
            "  c) Put a comma after transition words (சரி, புரிந்தது,).\n"
            "  d) Every reply 1 to 2 short sentences, maximum 15 words, plain text only."
        ),
        "example": "Worker: 'லைன் த்ரீ நின்னுடுச்சு, கியர்பாக்ஸ் போயிடுச்சு போல.' You: 'சரி, புரிந்தது. ஆனால் "
                   "கியர்பாக்ஸ் ஆறு நாள் முன்பு மாற்றப்பட்டது. பேனல் பி தெர்மல் ரிலே லைட் சிவப்பா?'",
        "speech": {
            "confirm": "சரி, புரிந்தது. டிக்கெட் நம்பர் {ticket} உருவாக்கி {part} ரிசர்வ் செய்யட்டுமா?",
            "routed": "நன்றி. டிக்கெட் நம்பர் {ticket} உருவாக்கப்பட்டது. நான் இப்போதே இன்ஜினியரை அழைத்து தெரிவிக்கிறேன். முப்பது நிமிடத்தில் மீண்டும் அழைக்கிறேன்.",
            "eta": "இன்ஜினியர் {eta} நிமிடத்தில் வந்துவிடுவார். அதுவரை லைனை ஆஃப் செய்தே வையுங்கள்.",
            "yes_words": ["ஆமாம்", "செய்யுங்கள்", "சரி", "Yes"],
        },
    },
    "en-IN": {
        "label": "English (India)",
        "short": "English",
        "asr_language": "en-IN",
        "llm_params": {"temperature": 0.30, "presence_penalty": 0.20, "max_tokens": 110},
        "voice_preference": ["en-IN-aarav"],
        "tts_params": {"voiceId": "en-IN-aarav", "locale": "en-IN", "style": MURF_STYLE, "rate": 3,
                       "pitch": -1, "sample_rate": 24000, "model": "falcon-2.1"},
        "vad_base": {"threshold": 0.52, "interrupt_duration_ms": 160, "prefix_padding_ms": 550,
                     "silence_duration_ms": 520},
        "speak_codes_phonetically": False,
        "keywords": [],
        "greeting": "Hi there! This is SyncUp. What issue are you seeing on the floor right now?",
        "failure": "Sorry, could you say that again?",
        "prompt_lang_instruction": (
            "Speak crisp, empathetic Indian workplace English with natural contractions (I've, let's, that's). "
            "Ask one sharp diagnostic question at a time. Never read record or part IDs aloud; say an error code once as "
            "'E zero four' and a ticket only as 'ticket number one zero four'. "
            "Every reply 1 to 2 short sentences, maximum 15 words, plain text only."
        ),
        "example": "",
        "speech": {
            "confirm": "Got it. Shall I raise ticket number {ticket} and reserve the {part}?",
            "routed": "Thanks. Ticket number {ticket} is raised. I'm calling the engineer right now, and I'll check back with you in 30 minutes.",
            "eta": "The engineer will be there in {eta} minutes. Please keep the line switched off until then.",
            "yes_words": ["yes", "go ahead", "do it", "okay"],
        },
    },
}

# Spoken names of the reserved part / responding team per SOP, so confirmation lines need no English nouns.
SOP_SPEECH: dict[str, dict[str, tuple[str, str]]] = {
    "E-04": {"ml-IN": ("തെർമൽ റിലേ", "ഇലക്ട്രിക്കൽ ടീം"), "kn-IN": ("ಥರ್ಮಲ್ ರಿಲೇ", "ಎಲೆಕ್ಟ್ರಿಕಲ್ ಟೀಮ್"),
             "ta-IN": ("தெர்மல் ரிலே", "எலக்ட்ரிகல் டீம்"), "hi-IN": ("thermal relay", "electrical team"),
             "en-IN": ("thermal relay", "the electrical team")},
    "NO_POWER": {"ml-IN": ("പി ഒ ഇ അഡാപ്റ്റർ", "ഐ ടി ടീം"), "kn-IN": ("ಪಿ ಒ ಇ ಅಡಾಪ್ಟರ್", "ಐ ಟಿ ಟೀಮ್"),
                 "ta-IN": ("பி ஓ இ அடாப்டர்", "ஐ டி டீம்"), "hi-IN": ("PoE adapter", "IT team"),
                 "en-IN": ("PoE adapter", "the IT team")},
}


def spoken_part_team(sop_code: str | None, language: str | None) -> tuple[str, str]:
    lang = language or settings.DEFAULT_LANGUAGE
    by_lang = SOP_SPEECH.get(sop_code or "", {})
    return by_lang.get(lang) or by_lang.get("en-IN") or ("spare part", "the maintenance team")


# Acoustic environment = offsets applied ON TOP of the language's vad_base (current v2 schema; the flat
# `agora_vad_config` form is MLLM-only/deprecated). Field mapping:
#   threshold -> speech_threshold, interrupt_duration_ms -> start_of_speech.vad_config,
#   speaking_interrupt_duration_ms = stricter barge-in WHILE the agent talks (kills speaker echo / PA bleed),
#   silence_duration_ms -> end_of_speech.vad_config.
# Soft-voice capture is handled on the client too: AGC + ANS + a gain boost on the mic track (see
# frontend useAgoraSession), so a quiet worker reaches ARES above the VAD threshold without lowering it into noise.
ACOUSTIC_PROFILES: dict[str, dict] = {
    "stage_noisy": {  # default: hackathon stage / factory floor with PA speakers
        "label": "Stage / Noisy",
        "threshold_delta": 0.10, "threshold_cap": 0.72, "interrupt_delta_ms": 80,
        "speaking_interrupt_extra_ms": 80, "silence_delta_ms": 0, "prefix_delta_ms": -50,
        "tts_volume_offset": -4,  # quieter agent on speakerphone/PA -> less echo -> no false self-interruptions
        "client_mic_gain": 140,
    },
    "quiet": {  # testing / quiet room: the language's calibrated base, untouched
        "label": "Quiet Room",
        "threshold_delta": 0.0, "threshold_cap": 0.72, "interrupt_delta_ms": 0,
        "speaking_interrupt_extra_ms": 40, "silence_delta_ms": 0, "prefix_delta_ms": 0,
        "tts_volume_offset": -4,  # laptop speakers still feed the mic; keep Murf a notch quieter
        "client_mic_gain": 100,
    },
    "soft_voice": {  # soft-spoken / distant worker: more sensitive, more patient end-of-turn
        "label": "Soft Voice",
        "threshold_delta": -0.13, "threshold_floor": 0.38, "threshold_cap": 0.72, "interrupt_delta_ms": 20,
        "speaking_interrupt_extra_ms": 60, "silence_delta_ms": 60, "prefix_delta_ms": 100,
        "tts_volume_offset": -4,
        "client_mic_gain": 220,
    },
}
DEFAULT_ENVIRONMENT = "stage_noisy"


def get_acoustics(environment: str | None) -> dict:
    return ACOUSTIC_PROFILES.get(environment or DEFAULT_ENVIRONMENT, ACOUSTIC_PROFILES[DEFAULT_ENVIRONMENT])


def get_profile(language: str | None) -> dict:
    return LANGUAGE_PROFILES.get(language or settings.DEFAULT_LANGUAGE, LANGUAGE_PROFILES[settings.DEFAULT_LANGUAGE])


def compute_tuning(language: str | None, environment: str | None) -> dict:
    """Effective per-session calibration = language base + acoustic-environment offsets. Single source of truth
    for the /join payload, the /api/session/start telemetry and the live pipeline log."""
    p, a = get_profile(language), get_acoustics(environment)
    v, tts, llm = p["vad_base"], p["tts_params"], p["llm_params"]
    threshold = min(a["threshold_cap"], max(a.get("threshold_floor", 0.0), v["threshold"] + a["threshold_delta"]))
    interrupt = v["interrupt_duration_ms"] + a["interrupt_delta_ms"]
    return {
        "language": language or settings.DEFAULT_LANGUAGE,
        "environment": environment or DEFAULT_ENVIRONMENT,
        "temperature": llm["temperature"],
        "presence_penalty": llm["presence_penalty"],
        "max_tokens": llm["max_tokens"],
        "voice": tts["voiceId"],
        "model": tts.get("model", settings.MURF_MODEL),
        "style": tts.get("style", MURF_STYLE),
        "rate": tts["rate"],
        "pitch": tts["pitch"],
        "volume_offset": a["tts_volume_offset"],
        "vad_threshold": round(threshold, 2),
        "interrupt_ms": interrupt,
        "speaking_interrupt_ms": interrupt + a["speaking_interrupt_extra_ms"],
        "prefix_ms": v["prefix_padding_ms"] + a["prefix_delta_ms"],
        "silence_ms": v["silence_duration_ms"] + a["silence_delta_ms"],
        "client_mic_gain": a["client_mic_gain"],
    }


def build_turn_detection(environment: str | None, language: str | None = None) -> dict:
    t = compute_tuning(language, environment)
    return {
        "mode": "default",
        "config": {
            "speech_threshold": t["vad_threshold"],
            "start_of_speech": {"mode": "vad", "vad_config": {
                "interrupt_duration_ms": t["interrupt_ms"],
                "speaking_interrupt_duration_ms": t["speaking_interrupt_ms"],
                "prefix_padding_ms": t["prefix_ms"],
            }},
            "end_of_speech": {"mode": "vad", "vad_config": {"silence_duration_ms": t["silence_ms"]}},
        },
    }


def build_tts_params(language: str | None, environment: str | None) -> dict:
    p, t = get_profile(language), compute_tuning(language, environment)
    params = {
        "api_key": settings.MURF_API_KEY,
        "base_url": settings.MURF_BASE_URL,
        "voiceId": t["voice"],
        "locale": p["tts_params"]["locale"],
        "model": t["model"],
        "style": t["style"],
        "rate": t["rate"],
        "pitch": t["pitch"],
        "sample_rate": p["tts_params"].get("sample_rate", 24000),
        # Murf Falcon 2.1: SAY_AS entries so codes the LLM writes (E-04, SYNC-104, TR-882...) are never read as
        # "minus"; lenient chunking starts audio without waiting on ambiguous sentence ends. Agora passes extra
        # params through to Murf unvalidated (docs: models/tts/murf).
        "pronunciation_dictionary": speech_normalizer.pronunciation_dictionary(language),
        "predictive_chunking": "lenient",
    }
    if t["volume_offset"] is not None:
        params["volume_offset"] = t["volume_offset"]
    return params


async def resolve_murf_voices() -> dict[str, str]:
    """Startup helper: pick the first voice in each profile's voice_preference that supports its locale on
    falcon-2.1; if none does, auto-pick a native voice for the locale (prefers one that also speaks en-IN)."""
    if not settings.MURF_API_KEY:
        return {}
    try:
        async with httpx.AsyncClient(timeout=6.0) as client:
            resp = await client.get(settings.MURF_VOICES_URL, params={"model": "falcon-2.1"},
                                    headers={"api-key": settings.MURF_API_KEY})
        resp.raise_for_status()
        voices = resp.json()
    except Exception as e:  # never block startup on Murf
        log.warning("Murf voice discovery skipped: %s", e)
        return {}

    def supports(v: dict, loc: str) -> bool:
        return v.get("locale") == loc or loc in (v.get("supportedLocales") or {})

    chosen = {}
    by_id = {v.get("voiceId"): v for v in voices}
    for code, prof in LANGUAGE_PROFILES.items():
        loc = prof["tts_params"]["locale"]
        pick = next((vid for vid in prof.get("voice_preference", []) + [prof["tts_params"]["voiceId"]]
                     if by_id.get(vid) and supports(by_id[vid], loc)), None)
        if not pick:
            candidates = [v for v in voices if supports(v, loc)]
            candidates.sort(key=lambda v: (v.get("locale") != loc, not supports(v, "en-IN")))
            pick = candidates[0]["voiceId"] if candidates else prof["tts_params"]["voiceId"]
        if pick != prof["tts_params"]["voiceId"]:
            log.info("Murf voice for %s: %s -> %s", code, prof["tts_params"]["voiceId"], pick)
            prof["tts_params"]["voiceId"] = pick
        chosen[code] = pick
    return chosen


def build_system_prompt(profile: dict, asset_hint: str | None) -> str:
    example = f"\nHOW YOU SOUND (example): {profile['example']}" if profile.get("example") else ""
    hint = f"The worker is most likely calling about {asset_hint}. " if asset_hint else ""
    yes = ", ".join(f"'{w}'" for w in profile["speech"]["yes_words"])
    lang = profile["short"]
    return f"""You are SyncUp, the friendly senior maintenance lead every shift trusts. You are on a voice call with a frontline worker on an Indian factory or warehouse floor. Their machine has a problem, they may be stressed, and they are speaking {lang}.

WHO YOU ARE
- A calm, kind, experienced colleague — never a robot, a form or a call-centre script.
- You respect the worker's experience. Their guesses are reasonable; you simply check them against the records together.
- You keep things moving: short sentences, one question at a time, no repetition, no filler.

LANGUAGE AND VOICE
{profile['prompt_lang_instruction']}
Everything you say is spoken aloud by a TTS voice, so write exactly what a person would say: no lists, no markdown, no emojis, no brackets, no English IDs.

{hint}Known machines: LINE-03 (Bosch Pack-400 packaging line, "Line 3") and GATE-02 (warehouse dispatch barcode scanner, "Gate 2").

HOW THE CALL FLOWS (one step per turn)
1. LISTEN. Let the worker describe what happened. If it is unclear which machine or what they saw, ask one simple, open question.
2. TRIAGE. As soon as you hear a problem, call triage_and_verify_claim. Write facts (what they saw: lights, codes, sounds, machine state), guesses (what they assume: "thonnunnu", "lagta hai", "maybe") and unknowns as short ENGLISH phrases, even though you speak {lang}. Pass fault_code if a code was mentioned, else "".
3. GENTLY CORRECT, THEN CHECK. Say the tool's "directive" in natural {lang}. If a guess was ruled out by a record, acknowledge it was a fair thought, give the reason in plain words ("the gearbox was replaced six days ago"), then ask the one check question.
4. PROPOSE, DON'T ACT. When the worker answers the check, call triage_and_verify_claim with the new fact, then call propose_critical_action. Ask its confirmation question exactly as given, then wait.
5. ACT ON A CLEAR YES. Only after an explicit yes ({yes}) call finalize_english_brief and say its line: the ticket is raised and you are calling the engineer now. If they say no or hesitate, ask kindly what they would like to change.
6. CLOSE WARMLY. If the worker thanks you or has nothing more, end with a short, warm line.

SPEAKING CODES LIKE A PERSON
- Never read record IDs, SOP codes or part numbers aloud (LOG-891, TR-882). Describe them instead: "the maintenance record from six days ago", "a spare thermal relay".
- Say an error code at most once, the way a technician would, using the spoken form from the tool.
- Say a ticket only as its number, using the tool's ticket_spoken form. Never say "SYNC", "hyphen" or "minus", and never spell letters one by one.

HARD RULES
- Every spoken reply MUST be 1 to 2 short sentences (maximum 15 words). Be warm, crisp, and direct. Never read raw hyphens or symbols. One question per turn.
- Never invent maintenance records, readings or people; only use what the tools return.
- Never call finalize_english_brief before an explicit yes to the proposal.
- Start with the most important words first; your reply is streamed to the voice sentence by sentence.
- If speech recognition looks garbled or very short, ask them to repeat in four words or fewer.{example}"""


def _tool_definitions(channel_name: str) -> list[dict]:
    base = settings.PUBLIC_WEBHOOK_BASE_URL
    ch = quote(channel_name, safe="")
    headers = {"Content-Type": "application/json", "X-SyncUp-Key": "{{template_variables.webhook_secret}}",
               "ngrok-skip-browser-warning": "true"}  # free ngrok otherwise may serve an HTML interstitial
    summary_priority = {
        "type": "object",
        "properties": {
            "summary": {"type": "string", "description": "One-sentence English summary of the issue."},
            "priority": {"type": "string", "enum": ["P1", "P2", "P3"],
                         "description": "P1 if production is stopped, P2 if degraded, P3 otherwise."},
        },
        "required": ["summary", "priority"],
    }

    def server(path: str, body: dict) -> dict:
        return {"method": "POST", "url": f"{base}{path}?channel={ch}", "headers": headers,
                "body": {**body, "tool_call_id": "{{tool_call_id}}"}, "timeout_ms": 2500}

    return [
        {
            "type": "function",
            "function": {
                "name": "triage_and_verify_claim",
                "description": "Record the worker's observed facts, guesses and unknowns (all in short English phrases) "
                               "and cross-check guesses against company maintenance logs and SOPs. Returns a "
                               "'directive' telling you what to say or ask next.",
                "parameters": {
                    "type": "object",
                    "properties": {
                        "asset_id": {"type": "string", "enum": ["LINE-03", "GATE-02"],
                                     "description": "Asset the worker is talking about."},
                        "verified_facts": {"type": "array", "items": {"type": "string"},
                                           "description": "Directly observed facts, English. Empty array if none."},
                        "worker_guesses": {"type": "array", "items": {"type": "string"},
                                           "description": "Unverified assumptions about the cause, English. Empty array if none."},
                        "missing_unknowns": {"type": "array", "items": {"type": "string"},
                                             "description": "Things still unknown that need checking, English. Empty array if none."},
                        "fault_code": {"type": "string", "description": "Error code mentioned, e.g. E-04; empty string if none."},
                    },
                    "required": ["asset_id", "verified_facts", "worker_guesses", "missing_unknowns", "fault_code"],
                },
            },
            "execution": {"mode": "sync"},
            "server": server("/tools/triage", {
                "asset_id": "{{args.asset_id}}",
                "verified_facts": "{{args.verified_facts}}",
                "worker_guesses": "{{args.worker_guesses}}",
                "missing_unknowns": "{{args.missing_unknowns}}",
                "fault_code": "{{args.fault_code}}",
            }),
        },
        {
            "type": "function",
            "function": {
                "name": "propose_critical_action",
                "description": "Diagnostics are complete: draft the work order and spare-part reservation and put it "
                               "on hold for the worker's approval. Returns the exact confirmation question to ask. "
                               "Call after the worker answered the diagnostic check question; never skip it.",
                "parameters": summary_priority,
            },
            "execution": {"mode": "sync"},
            "server": server("/tools/propose_action", {"summary": "{{args.summary}}", "priority": "{{args.priority}}"}),
        },
        {
            "type": "function",
            "function": {
                "name": "finalize_english_brief",
                "description": "Execute the approved action: route the English engineering ticket, reserve the part "
                               "and schedule the follow-up. Call ONLY after the worker said yes to the proposal.",
                "parameters": summary_priority,
            },
            "execution": {"mode": "sync"},
            "server": server("/tools/route", {"summary": "{{args.summary}}", "priority": "{{args.priority}}"}),
        },
    ]


def build_llm_config(channel_name: str, profile: dict, asset_hint: str | None) -> dict:
    llm = {
        "vendor": "openai",
        "style": "openai",
        "url": settings.LLM_API_URL,
        "params": {"model": settings.LLM_MODEL, **profile["llm_params"]},
        "system_messages": [{"role": "system", "content": build_system_prompt(profile, asset_hint)}],
        "greeting_message": profile["greeting"],
        "failure_message": profile["failure"],
        "max_history": 10,  # shorter context = lower LLM time-to-first-token
        "template_variables": {"webhook_secret": settings.WEBHOOK_SECRET or "unset"},
        "tools": _tool_definitions(channel_name),
    }
    if settings.LLM_CREDENTIAL_MODE == "byok" and settings.LLM_API_KEY:
        llm["credential_mode"] = "byok"
        llm["api_key"] = settings.LLM_API_KEY
    else:
        llm["credential_mode"] = "managed"  # Agora-hosted model, no key required
    return llm


def build_join_payload(channel_name: str, agent_rtc_token: str, language: str | None = None,
                       asset_hint: str | None = None, environment: str | None = None) -> dict:
    profile = get_profile(language)
    return {
        "name": f"syncup-{channel_name}-{int(time.time())}",
        "properties": {
            "channel": channel_name,
            "token": agent_rtc_token,
            "agent_rtc_uid": str(settings.AGENT_UID),
            "remote_rtc_uids": [str(settings.USER_UID)],
            "enable_string_uid": False,
            "idle_timeout": 120,
            # enable_rtm + data_channel=rtm: Agora pushes user/assistant transcription, agent state (presence)
            # and per-module latency metrics to the browser over RTM. Requires RTC+RTM (007) tokens.
            # enable_sal + sal.locking = Agora's current "AI VAD / background-voice suppression": the agent locks
            # onto the worker's voice and blocks ~95% of other voices, PA echo and noise (docs: properties.sal).
            "advanced_features": {"enable_tools": True, "enable_rtm": True, "enable_sal": True},
            "sal": {"sal_mode": "locking"},
            # v2.6+: interruption moved out of turn_detection (legacy interrupt_mode "interrupt" == start_of_speech).
            "interruption": {"enable": True, "mode": "start_of_speech"},
            "parameters": {
                "data_channel": "rtm",
                "enable_metrics": True,
                "enable_error_message": True,
                "audio_scenario": "aiserver",  # Agora's latency + loss-resilience tuned path for AI agents
            },
            "asr": {
                "vendor": "ares",
                "language": profile["asr_language"],
                "keywords": BASE_KEYWORDS + profile.get("keywords", []),
            },
            "turn_detection": build_turn_detection(environment, language),
            "llm": build_llm_config(channel_name, profile, asset_hint),
            "tts": {"vendor": "murf", "params": build_tts_params(language, environment)},
        },
    }


class AgoraConvoError(RuntimeError):
    def __init__(self, status_code: int, detail: str):
        super().__init__(f"Agora ConvoAI error {status_code}: {detail}")
        self.status_code = status_code
        self.detail = detail


def _basic_auth_header() -> dict[str, str]:
    raw = f"{settings.AGORA_CUSTOMER_ID}:{settings.AGORA_CUSTOMER_SECRET}".encode()
    return {"Authorization": "Basic " + base64.b64encode(raw).decode(), "Content-Type": "application/json"}


async def start_convo_agent(channel_name: str, agent_rtc_token: str, language: str | None = None,
                            asset_hint: str | None = None, environment: str | None = None) -> dict:
    url = f"{AGORA_API_BASE}/{settings.AGORA_APP_ID}/join"
    payload = build_join_payload(channel_name, agent_rtc_token, language, asset_hint, environment)
    async with httpx.AsyncClient(timeout=15.0) as client:
        resp = await client.post(url, headers=_basic_auth_header(), json=payload)
    if resp.status_code >= 400:
        raise AgoraConvoError(resp.status_code, resp.text)
    return resp.json()


async def stop_convo_agent(agent_id: str) -> dict:
    url = f"{AGORA_API_BASE}/{settings.AGORA_APP_ID}/agents/{agent_id}/leave"
    async with httpx.AsyncClient(timeout=10.0) as client:
        resp = await client.post(url, headers=_basic_auth_header())
    if resp.status_code >= 400:
        raise AgoraConvoError(resp.status_code, resp.text)
    return resp.json() if resp.content else {"agent_id": agent_id}


async def speak_agent(agent_id: str, text: str, priority: str = "INTERRUPT") -> dict:
    """Make the live agent say `text` through Murf (Agora /speak; max 512 UTF-8 bytes)."""
    encoded = text.encode("utf-8")
    if len(encoded) > 512:
        text = encoded[:512].decode("utf-8", errors="ignore")
    url = f"{AGORA_API_BASE}/{settings.AGORA_APP_ID}/agents/{agent_id}/speak"
    async with httpx.AsyncClient(timeout=6.0) as client:
        resp = await client.post(url, headers=_basic_auth_header(),
                                 json={"text": text, "priority": priority, "interruptable": True})
    if resp.status_code >= 400:
        raise AgoraConvoError(resp.status_code, resp.text)
    return resp.json() if resp.content else {}


# ----------------------------------------------------------------------------- outbound engineer call (English)
# After the worker approves, SyncUp phones the on-call engineer: a second ConvoAI agent on its own Agora channel,
# speaking Indian English through Murf, with one tool to record the engineer's commitment (ETA). The browser joins
# that channel as the "engineer's handset", so judges hear the call and can answer as the engineer.
ENGINEERS: dict[str, dict] = {
    "Electrical & Controls Maintenance": {"name": "Arjun M.", "first": "Arjun", "honorific": "sir",
                                          "role": "Lead Engineer", "team": "Electrical & Controls"},
    "Warehouse IT & Infra": {"name": "Priya Menon", "first": "Priya", "honorific": "ma'am",
                             "role": "On-call IT Infrastructure Engineer", "team": "Warehouse IT & Infra"},
    "Shift Maintenance Supervisor": {"name": "Anil Kumar", "first": "Anil", "honorific": "sir",
                                     "role": "Shift Maintenance Supervisor", "team": "Shift Maintenance"},
}


def engineer_for(team: str | None) -> dict:
    return ENGINEERS.get(team or "", ENGINEERS["Shift Maintenance Supervisor"])


def build_engineer_prompt(eng: dict, briefing: dict) -> str:
    facts = "; ".join(briefing["facts"]) or "none recorded"
    ruled_out = "; ".join(briefing["ruled_out"]) or "nothing"
    return f"""You are SyncUp, an AI shift assistant, on an OUTBOUND phone call to {eng['name']}, the {eng['role']}, escalating a confirmed fault from the shop floor.
{briefing.get('language_rule') or "You speak polished, warm, professional Indian English, like a capable colleague who respects the engineer's time."} Call them by first name, {eng['first']}.

THE ESCALATION (the only facts you may use; never invent others)
- Machine: {briefing['asset']}
- Problem: {briefing['problem']}
- Confirmed on the floor by {briefing['worker']}: {facts}
- Ruled out: {ruled_out}
- Ticket: number {briefing['ticket_spoken']}, {briefing['priority_spoken']}
- Spare part reserved: {briefing['part_spoken']}
- Recommended action: {briefing['action']}

You already opened the call with a short briefing and asked them to confirm dispatch. Now:
1. If they ask questions, answer briefly from the facts above. If you don't know, say so and offer to check with the operator.
2. Make sure you know whether they will attend and roughly how many minutes they need.
3. As soon as they commit or decline, call acknowledge_escalation (eta_minutes 0 if unknown, accepted true or false, short English notes).
4. Then thank them, say you will update the operator in their own language, and say a one-line goodbye.

STYLE: Every spoken reply MUST be 1 to 2 short sentences (maximum 15 words). Be warm, crisp, and direct. Never read raw hyphens or symbols. One question at a time; no lists or markdown. Say the ticket only as "ticket number {briefing['ticket_spoken']}". Read the part number only if asked, as "{briefing['part_code_spoken']}". Never say "hyphen" or "minus"."""


def build_engineer_join_payload(channel_name: str, agent_rtc_token: str, source_channel: str, eng: dict,
                                briefing: dict, environment: str | None = None, language: str = "en-IN") -> dict:
    profile = get_profile(language)
    base, src = settings.PUBLIC_WEBHOOK_BASE_URL, quote(source_channel, safe="")
    headers = {"Content-Type": "application/json", "X-SyncUp-Key": "{{template_variables.webhook_secret}}",
               "ngrok-skip-browser-warning": "true"}
    tool = {
        "type": "function",
        "function": {
            "name": "acknowledge_escalation",
            "description": "Record the engineer's answer to the escalation: whether they accept and their ETA in minutes.",
            "parameters": {
                "type": "object",
                "properties": {
                    "eta_minutes": {"type": "integer", "description": "Minutes until the engineer arrives; 0 if unknown."},
                    "accepted": {"type": "boolean", "description": "True if the engineer or their team will attend."},
                    "notes": {"type": "string", "description": "Short English note of anything else they said; empty if none."},
                },
                "required": ["eta_minutes", "accepted", "notes"],
            },
        },
        "execution": {"mode": "sync"},
        "server": {"method": "POST", "url": f"{base}/tools/engineer_ack?channel={src}", "headers": headers,
                   "body": {"eta_minutes": "{{args.eta_minutes}}", "accepted": "{{args.accepted}}",
                            "notes": "{{args.notes}}", "tool_call_id": "{{tool_call_id}}"},
                   "timeout_ms": 2500},
    }
    llm = {
        "vendor": "openai",
        "style": "openai",
        "url": settings.LLM_API_URL,
        "params": {"model": settings.LLM_MODEL, **profile["llm_params"]},
        "system_messages": [{"role": "system", "content": build_engineer_prompt(eng, briefing)}],
        "greeting_message": briefing["opener"],
        "failure_message": profile["failure"],
        "max_history": 12,
        "template_variables": {"webhook_secret": settings.WEBHOOK_SECRET or "unset"},
        "tools": [tool],
        "credential_mode": "managed",
    }
    if settings.LLM_CREDENTIAL_MODE == "byok" and settings.LLM_API_KEY:
        llm.update(credential_mode="byok", api_key=settings.LLM_API_KEY)
    tts = build_tts_params(language, environment)
    if language == "en-IN":
        tts["rate"] = 0  # a touch calmer than the en-IN default (+3) for a formal briefing
    return {
        "name": f"syncup-eng-{channel_name}-{int(time.time())}",
        "properties": {
            "channel": channel_name,
            "token": agent_rtc_token,
            "agent_rtc_uid": str(settings.AGENT_UID),
            "remote_rtc_uids": [str(settings.USER_UID)],
            "enable_string_uid": False,
            "idle_timeout": 60,
            "advanced_features": {"enable_tools": True, "enable_sal": True},
            "sal": {"sal_mode": "locking"},
            "interruption": {"enable": True, "mode": "start_of_speech"},
            "parameters": {"enable_metrics": True, "audio_scenario": "aiserver"},
            "asr": {"vendor": "ares", "language": profile["asr_language"], "keywords": BASE_KEYWORDS},
            "turn_detection": build_turn_detection(environment, language),
            "llm": llm,
            "tts": {"vendor": "murf", "params": tts},
        },
    }


async def start_engineer_agent(channel_name: str, agent_rtc_token: str, source_channel: str, eng: dict,
                               briefing: dict, environment: str | None = None, language: str = "en-IN") -> dict:
    url = f"{AGORA_API_BASE}/{settings.AGORA_APP_ID}/join"
    payload = build_engineer_join_payload(channel_name, agent_rtc_token, source_channel, eng, briefing, environment,
                                          language)
    async with httpx.AsyncClient(timeout=15.0) as client:
        resp = await client.post(url, headers=_basic_auth_header(), json=payload)
    if resp.status_code >= 400:
        raise AgoraConvoError(resp.status_code, resp.text)
    return resp.json()


async def get_history(agent_id: str, client: httpx.AsyncClient | None = None) -> list[dict] | None:
    """Conversation so far (Agora GET /agents/{id}/history): [{role: user|assistant, content}], None if gone."""
    url = f"{AGORA_API_BASE}/{settings.AGORA_APP_ID}/agents/{agent_id}/history"
    if client is None:
        async with httpx.AsyncClient(timeout=3.0) as c:
            resp = await c.get(url, headers=_basic_auth_header())
    else:
        resp = await client.get(url, headers=_basic_auth_header(), timeout=3.0)
    if resp.status_code != 200:
        return None
    return [c for c in resp.json().get("contents", [])
            if c.get("role") in ("user", "assistant") and str(c.get("content") or "").strip()]
