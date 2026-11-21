"""Deterministic code-to-speech normalizer so Murf Falcon 2.1 never reads '-' as "minus" or stumbles over codes.

    normalize_for_speech("Line 3 stopped with E-04, ticket SYNC-104", "en-IN")
      -> "Line three stopped with E zero four, ticket Sync one zero four"
    normalize_for_speech("LOG-891", "ml-IN") -> "ലോഗ് എയ്റ്റ് നയൻ വൺ"

Used for every line the backend makes the agent say (greetings, confirmations, /speak, the engineer briefing) and
to build Murf's pronunciation_dictionary (SAY_AS), which also catches codes the LLM writes on its own.
"""
import re

import phonetics

_EN_DIGITS = {"0": "zero", "1": "one", "2": "two", "3": "three", "4": "four", "5": "five", "6": "six",
              "7": "seven", "8": "eight", "9": "nine"}
_EN_WORDS = {"SYNC": "Sync", "LOG": "Log", "LINE": "Line", "GATE": "Gate", "PANEL": "Panel", "PART": "Part",
             "NO": "no", "POWER": "power"}

# Machine names: humans say "Line three", not "Line zero three".
_ASSET_RE = re.compile(r"\b(LINE|Line|line|GATE|Gate|gate)[\s\-_]?0*(\d{1,2})\b")
# Ticket / record numbers written after a prefix word: "ticket 104", "SYNC 104".
_PREFIXED_NUM_RE = re.compile(r"\b(ticket|Ticket|SYNC|Sync|LOG|Log)\s+(\d{2,})\b")
_POE_RE = re.compile(r"\bPOE-?24V\b", re.IGNORECASE)

_GLOSSARY = {  # English technical words -> native script (spoken in a Malayalam sentence)
    "ml": [("thermal relay", "തെർമൽ റിലേ"), ("Thermal Relay", "തെർമൽ റിലേ"), ("gearbox", "ഗിയർബോക്സ്"),
           ("Gearbox", "ഗിയർബോക്സ്"), ("Panel B", "പാനൽ ബി"), ("panel B", "പാനൽ ബി")],
}
_POE_SPOKEN = {"en": "P O E twenty four volt", "ml": "പി ഒ ഇ ട്വന്റി ഫോർ വോൾട്ട്",
               "kn": "ಪಿ ಒ ಇ ಟ್ವೆಂಟಿ ಫೋರ್ ವೋಲ್ಟ್", "ta": "பி ஓ இ ட்வென்டி ஃபோர் வோல்ட்"}
_ASSET_WORD = {"ml": {"LINE": "ലൈൻ", "GATE": "ഗേറ്റ്"}, "kn": {"LINE": "ಲೈನ್", "GATE": "ಗೇಟ್"},
               "ta": {"LINE": "லைன்", "GATE": "கேட்"}}


def _lang(language: str | None) -> str:
    return (language or "en-IN").split("-")[0].lower()


def _digit_words(digits: str, lang: str) -> str:
    table = phonetics._TABLES.get(lang)  # noqa: SLF001 (shared spelling tables)
    words = table["digits"] if table else _EN_DIGITS
    return " ".join(words[d] for d in digits)


def speak_code(code: str, language: str | None = "en-IN") -> str:
    """One code -> words: 'E-04' -> 'E zero four' / 'ഇ സീറോ ഫോർ'; 'SYNC-104' -> 'Sync one zero four'."""
    lang = _lang(language)
    if _POE_RE.fullmatch(code):
        return _POE_SPOKEN.get(lang, _POE_SPOKEN["en"])
    m = _ASSET_RE.fullmatch(code)
    if m:
        return _asset(m, lang)
    if lang in phonetics._TABLES:  # noqa: SLF001
        return phonetics.speak(code, language)
    out: list[str] = []
    for token in re.findall(r"[A-Za-z]+|\d", code):
        up = token.upper()
        if token.isdigit():
            out.append(_EN_DIGITS[token])
        elif up in _EN_WORDS:
            out.append(_EN_WORDS[up])
        else:
            out.append(" ".join(up))
    return " ".join(out)


def _asset(m: re.Match, lang: str) -> str:
    kind, num = m.group(1).upper(), str(int(m.group(2)))
    word = _ASSET_WORD.get(lang, {}).get(kind, kind.capitalize())
    if len(num) == 1 or lang not in phonetics._TABLES:  # noqa: SLF001
        spoken = " ".join(_EN_DIGITS[d] for d in num) if lang not in phonetics._TABLES else _digit_words(num, lang)  # noqa: SLF001
    else:
        spoken = _digit_words(num, lang)
    return f"{word} {spoken}"


def normalize_for_speech(text: str, lang: str | None = "en-IN") -> str:
    """Rewrite every code / machine name / prefixed number in `text` into words the TTS voice reads cleanly."""
    if not text:
        return text
    lk = _lang(lang)
    out = _POE_RE.sub(lambda m: _POE_SPOKEN.get(lk, _POE_SPOKEN["en"]), text)
    out = _ASSET_RE.sub(lambda m: _asset(m, lk), out)
    out = phonetics.CODE_RE.sub(lambda m: speak_code(m.group(0).lstrip("#"), lang), out)
    out = _PREFIXED_NUM_RE.sub(lambda m: f"{m.group(1)} {_digit_words(m.group(2), lk)}", out)
    for src, dst in _GLOSSARY.get(lk, []):
        out = out.replace(src, dst)
    return re.sub(r"\s{2,}", " ", out)


def pronunciation_dictionary(language: str | None, ticket_range: range = range(100, 160)) -> dict[str, dict]:
    """Murf Falcon 2.1 `pronunciation_dictionary` (SAY_AS) for every code the agent may say, incl. future tickets."""
    codes = ["E-04", "LINE-03", "GATE-02", "LOG-891", "LOG-904", "TR-882", "POE-24V", "SRV-BLR-01"]
    codes += [f"SYNC-{n}" for n in ticket_range]
    return {c: {"type": "SAY_AS", "pronunciation": speak_code(c, language)} for c in codes}
