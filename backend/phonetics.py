"""Speech-friendly native-script spellings of alphanumeric codes for TTS (Malayalam, Kannada, Tamil).

Murf reads 'E-04' as "E minus zero four" and stumbles on 'SYNC-104'. Tool responses therefore carry a spoken
form the LLM says aloud, while the UI keeps showing the exact code:
    E-04     -> ഇ സീറോ ഫോർ          (ml-IN)   ಇ ಜೀರೋ ಫೋರ್ (kn-IN)   இ ஜீரோ ஃபோர் (ta-IN)
    SYNC-104 -> സിങ്ക് വൺ സീറോ ഫോർ
    LOG-891  -> ലോഗ് എയ്റ്റ് നൈൻ വൺ
Whole words we know (SYNC, LOG, LINE, ...) are spoken as words; other letter runs are spelled letter by letter;
digits are always read one by one (codes, not quantities). Languages without a table (hi-IN, en-IN) get the code
with hyphens replaced by spaces ("SYNC 104"), which their TTS voices read cleanly.
"""
import re

_TABLES: dict[str, dict[str, dict[str, str]]] = {
    "ml": {
        "letters": {
            "A": "എ", "B": "ബി", "C": "സി", "D": "ഡി", "E": "ഇ", "F": "എഫ്", "G": "ജി", "H": "എച്ച്", "I": "ഐ",
            "J": "ജെ", "K": "കെ", "L": "എൽ", "M": "എം", "N": "എൻ", "O": "ഒ", "P": "പി", "Q": "ക്യൂ", "R": "ആർ",
            "S": "എസ്", "T": "ടി", "U": "യു", "V": "വി", "W": "ഡബ്ല്യു", "X": "എക്സ്", "Y": "വൈ", "Z": "സെഡ്"},
        "digits": {"0": "സീറോ", "1": "വൺ", "2": "ടു", "3": "ത്രീ", "4": "ഫോർ", "5": "ഫൈവ്", "6": "സിക്സ്",
                   "7": "സെവൻ", "8": "എയ്റ്റ്", "9": "നയൻ"},
        "words": {"SYNC": "സിങ്ക്", "LOG": "ലോഗ്", "LINE": "ലൈൻ", "GATE": "ഗേറ്റ്", "PANEL": "പാനൽ",
                  "PART": "പാർട്ട്", "POE": "പി ഒ ഇ", "SRV": "എസ് ആർ വി", "BLR": "ബി എൽ ആർ", "NO": "നോ",
                  "POWER": "പവർ", "LED": "എൽ ഇ ഡി"},
    },
    "kn": {
        "letters": {
            "A": "ಎ", "B": "ಬಿ", "C": "ಸಿ", "D": "ಡಿ", "E": "ಇ", "F": "ಎಫ್", "G": "ಜಿ", "H": "ಎಚ್", "I": "ಐ",
            "J": "ಜೆ", "K": "ಕೆ", "L": "ಎಲ್", "M": "ಎಂ", "N": "ಎನ್", "O": "ಒ", "P": "ಪಿ", "Q": "ಕ್ಯೂ", "R": "ಆರ್",
            "S": "ಎಸ್", "T": "ಟಿ", "U": "ಯು", "V": "ವಿ", "W": "ಡಬ್ಲ್ಯೂ", "X": "ಎಕ್ಸ್", "Y": "ವೈ", "Z": "ಜೆಡ್"},
        "digits": {"0": "ಜೀರೋ", "1": "ಒನ್", "2": "ಟು", "3": "ತ್ರೀ", "4": "ಫೋರ್", "5": "ಫೈವ್", "6": "ಸಿಕ್ಸ್",
                   "7": "ಸೆವೆನ್", "8": "ಏಟ್", "9": "ನೈನ್"},
        "words": {"SYNC": "ಸಿಂಕ್", "LOG": "ಲಾಗ್", "LINE": "ಲೈನ್", "GATE": "ಗೇಟ್", "PANEL": "ಪ್ಯಾನಲ್",
                  "PART": "ಪಾರ್ಟ್", "POE": "ಪಿ ಒ ಇ", "SRV": "ಎಸ್ ಆರ್ ವಿ", "BLR": "ಬಿ ಎಲ್ ಆರ್", "NO": "ನೋ",
                  "POWER": "ಪವರ್", "LED": "ಎಲ್ ಇ ಡಿ"},
    },
    "ta": {
        "letters": {
            "A": "ஏ", "B": "பி", "C": "சி", "D": "டி", "E": "இ", "F": "எஃப்", "G": "ஜி", "H": "ஹெச்", "I": "ஐ",
            "J": "ஜே", "K": "கே", "L": "எல்", "M": "எம்", "N": "என்", "O": "ஓ", "P": "பி", "Q": "க்யூ", "R": "ஆர்",
            "S": "எஸ்", "T": "டி", "U": "யூ", "V": "வி", "W": "டபிள்யூ", "X": "எக்ஸ்", "Y": "ஒய்", "Z": "இசட்"},
        "digits": {"0": "ஜீரோ", "1": "ஒன்", "2": "டூ", "3": "த்ரீ", "4": "ஃபோர்", "5": "ஃபைவ்", "6": "சிக்ஸ்",
                   "7": "செவன்", "8": "எய்ட்", "9": "நைன்"},
        "words": {"SYNC": "சிங்க்", "LOG": "லாக்", "LINE": "லைன்", "GATE": "கேட்", "PANEL": "பேனல்",
                  "PART": "பார்ட்", "POE": "பி ஓ இ", "SRV": "எஸ் ஆர் வி", "BLR": "பி எல் ஆர்", "NO": "நோ",
                  "POWER": "பவர்", "LED": "எல் இ டி"},
    },
}
LANGUAGE_NAMES = {"ml": "Malayalam", "kn": "Kannada", "ta": "Tamil"}

# Back-compat aliases (Malayalam tables)
LETTERS_ML, DIGITS_ML, WORDS_ML = (_TABLES["ml"][k] for k in ("letters", "digits", "words"))

# Codes worth normalising: letters + digits joined by '-' / '#' (E-04, SYNC-104, LOG-891, TR-882, LINE-03, NO_POWER)
CODE_RE = re.compile(r"#?\b[A-Z]{1,6}(?:[-_#][A-Z0-9]+)+\b|#?\b[A-Z]{1,4}\d+\b")


def _key(language: str | None) -> str:
    return (language or "ml-IN").split("-")[0].lower()


def has_table(language: str | None) -> bool:
    return _key(language) in _TABLES


def speak(code: str, language: str | None = "ml-IN") -> str:
    """Native-script phonetic rendering of one code, e.g. ('E-04', 'kn-IN') -> 'ಇ ಜೀರೋ ಫೋರ್'."""
    table = _TABLES.get(_key(language))
    if not table:
        return re.sub(r"[-_#]+", " ", code).strip()
    out: list[str] = []
    for token in re.findall(r"[A-Za-z]+|\d", code):
        up = token.upper()
        if up in table["words"]:
            out.append(table["words"][up])
        elif up.isdigit():
            out.append(table["digits"][up])
        else:
            out.extend(table["letters"].get(ch, ch) for ch in up)
    return " ".join(out)


def speak_ml(code: str) -> str:
    return speak(code, "ml-IN")


def find_codes(text: str) -> list[str]:
    seen: list[str] = []
    for m in CODE_RE.findall(text or ""):
        m = m.lstrip("#")
        if m not in seen:
            seen.append(m)
    return seen


def spoken_hints(*texts: str, language: str | None = "ml-IN") -> dict[str, str]:
    """{exact code: native spoken form} for every code found in the given texts."""
    hints: dict[str, str] = {}
    for t in texts:
        for code in find_codes(t):
            hints.setdefault(code, speak(code, language))
    return hints


def annotate(label: str, code: str, language: str | None = "ml-IN") -> str:
    """'Ticket ID: SYNC-104 (spoken in Malayalam: സിങ്ക് വൺ സീറോ ഫോർ)'"""
    name = LANGUAGE_NAMES.get(_key(language), "the worker's language")
    return f"{label}: {code} (spoken in {name}: {speak(code, language)})"


# ----------------------------------------------------------------------------- human-style speech helpers
# People don't read "SYNC-104" or "LOG-891" aloud. They say "ticket number one-zero-four" and "the maintenance
# record from six days ago". These helpers produce what a senior technician would actually say.
_EN_DIGITS = {"0": "zero", "1": "one", "2": "two", "3": "three", "4": "four", "5": "five", "6": "six",
              "7": "seven", "8": "eight", "9": "nine"}


def speak_ticket(ticket_id: str, language: str | None = "ml-IN") -> str:
    """Only the number, digit by digit, in the listener's language: 'SYNC-104' -> 'വൺ സീറോ ഫോർ' / 'one zero four'."""
    digits = "".join(ch for ch in ticket_id if ch.isdigit()) or ticket_id
    table = _TABLES.get(_key(language))
    words = table["digits"] if table else _EN_DIGITS
    return " ".join(words.get(d, d) for d in digits)


def speak_en(code: str) -> str:
    """English spoken form for engineers: 'TR-882' -> 'T R eight eight two', 'E-04' -> 'E zero four'."""
    out: list[str] = []
    for token in re.findall(r"[A-Za-z]+|\d", code):
        if token.isdigit():
            out.append(_EN_DIGITS[token])
        else:
            out.append(" ".join(token.upper()))
    return " ".join(out)


def natural_status(status: str) -> str:
    """'HEALTHY - Newly Replaced' -> 'newly replaced and healthy'."""
    s = status.lower()
    if "replaced" in s:
        return "newly replaced and healthy"
    if "online" in s:
        return "online and healthy"
    return s.replace(" - ", ", ")


ETA_WORDS = {
    "ml": {5: "അഞ്ച്", 10: "പത്ത്", 15: "പതിനഞ്ച്", 20: "ഇരുപത്", 25: "ഇരുപത്തഞ്ച്", 30: "മുപ്പത്", 45: "നാല്പത്തഞ്ച്"},
    "kn": {5: "ಐದು", 10: "ಹತ್ತು", 15: "ಹದಿನೈದು", 20: "ಇಪ್ಪತ್ತು", 25: "ಇಪ್ಪತ್ತೈದು", 30: "ಮೂವತ್ತು", 45: "ನಲವತ್ತೈದು"},
    "ta": {5: "ஐந்து", 10: "பத்து", 15: "பதினைந்து", 20: "இருபது", 25: "இருபத்தைந்து", 30: "முப்பது", 45: "நாற்பத்தைந்து"},
    "hi": {5: "पाँच", 10: "दस", 15: "पंद्रह", 20: "बीस", 25: "पच्चीस", 30: "तीस", 45: "पैंतालीस"},
}


def speak_minutes(minutes: int, language: str | None) -> str:
    return ETA_WORDS.get(_key(language), {}).get(int(minutes), str(int(minutes)))
