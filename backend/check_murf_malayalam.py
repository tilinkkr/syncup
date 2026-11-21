"""List Murf Falcon 2.1 voices that can speak Malayalam (ml-IN).

Run: backend\\.venv\\Scripts\\python.exe backend\\check_murf_malayalam.py
Native voices (locale ml-IN) are listed first; multi-native voices that also support ml-IN follow.
"""
import sys
from pathlib import Path

import httpx

sys.path.insert(0, str(Path(__file__).resolve().parent))
import settings  # noqa: E402

TARGET = "ml-IN"


def main() -> int:
    if not settings.MURF_API_KEY:
        print("MURF_API_KEY is not set in backend/.env")
        return 1
    resp = httpx.get(settings.MURF_VOICES_URL, params={"model": "falcon-2.1"},
                     headers={"api-key": settings.MURF_API_KEY}, timeout=10)
    if resp.status_code != 200:
        print(f"Murf API error {resp.status_code}: {resp.text[:300]}")
        return 1
    voices = resp.json()

    def supports(v: dict) -> bool:
        return (str(v.get("locale", "")).startswith(TARGET) or str(v.get("voiceId", "")).startswith(TARGET)
                or TARGET in (v.get("supportedLocales") or {}))

    matches = sorted((v for v in voices if supports(v)),
                     key=lambda v: (not str(v.get("voiceId", "")).startswith(TARGET), v.get("voiceId", "")))
    print(f"{len(voices)} Falcon 2.1 voices on this key; {len(matches)} can speak {TARGET}:\n")
    print(f"{'voiceId':<22}{'displayName':<18}{'gender':<8}{'native':<8}styles")
    print("-" * 72)
    for v in matches:
        native = "yes" if str(v.get("voiceId", "")).startswith(TARGET) else "multi"
        styles = ", ".join(((v.get("supportedLocales") or {}).get(TARGET) or {}).get("availableStyles", [])
                           or v.get("availableStyles", []))
        print(f"{v.get('voiceId', ''):<22}{v.get('displayName', ''):<18}{v.get('gender', ''):<8}{native:<8}{styles}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
