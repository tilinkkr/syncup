"""Malayalam pronunciation check: synthesize one normalized sentence with the live ml-IN profile and save a WAV.

Run:  backend\\.venv\\Scripts\\python.exe backend\\test_malayalam_audio.py ["optional custom sentence"]
Uses Murf's streaming WebSocket (the same India-edge endpoint, voice, model, locale, rate and pitch that Agora
ConvoAI uses at runtime), so the file you hear is exactly what the live agent will sound like.
Output: backend/sample_ml.wav (24 kHz, 16-bit mono PCM).
"""
import asyncio
import base64
import json
import sys
import time
import wave
from pathlib import Path
from urllib.parse import urlencode

import websockets

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
import agora_convo  # noqa: E402
import settings  # noqa: E402

SENTENCE = ("ശരി, മനസ്സിലായി. പക്ഷേ, ലൈൻ ത്രീയിലെ ഗിയർബോക്സ് ആറു ദിവസം മുമ്പ് മാറ്റിയതാണ്. "
            "പാനൽ ബി-യിലെ തെർമൽ റിലേ ലൈറ്റ് ചുവപ്പാണോ എന്ന് ഒന്ന് നോക്കാമോ?")
OUT = HERE / "sample_ml.wav"
SAMPLE_RATE = 24000


async def synthesize(text: str) -> tuple[bytes, int | None]:
    env = sys.argv[2] if len(sys.argv) > 2 else "quiet"  # "stage_noisy" adds volume_offset -4
    t = agora_convo.build_tts_params("ml-IN", env)
    query = urlencode({"api-key": settings.MURF_API_KEY, "model": t["model"],
                       "sample_rate": SAMPLE_RATE, "channel_type": "MONO", "format": "PCM"})
    voice_config = {"voiceId": t["voiceId"], "multiNativeLocale": t["locale"], "style": t["style"],
                    "rate": t["rate"], "pitch": t["pitch"]}
    if "volume_offset" in t:
        voice_config["volume_offset"] = t["volume_offset"]
    print(f"voice={t['voiceId']} model={t['model']} locale={t['locale']} style={t['style']} rate={t['rate']} "
          f"pitch={t['pitch']} vol={t.get('volume_offset', 0)} env={env} edge={settings.MURF_BASE_URL}")
    pcm, ttfa = bytearray(), None
    async with websockets.connect(f"{settings.MURF_BASE_URL}?{query}", open_timeout=10) as ws:
        t0 = time.perf_counter()
        await ws.send(json.dumps({"voice_config": voice_config}))
        await ws.send(json.dumps({"text": text, "end": True}))
        while True:
            msg = json.loads(await asyncio.wait_for(ws.recv(), 20))
            if "audio" in msg:
                ttfa = ttfa or round((time.perf_counter() - t0) * 1000)
                pcm += base64.b64decode(msg["audio"])
            if "error" in str(msg).lower():
                raise RuntimeError(f"Murf error: {str(msg)[:300]}")
            if msg.get("final"):
                break
    return bytes(pcm), ttfa


def main() -> int:
    if not settings.MURF_API_KEY:
        print("MURF_API_KEY is not set in backend/.env")
        return 1
    text = sys.argv[1] if len(sys.argv) > 1 else SENTENCE
    pcm, ttfa = asyncio.run(synthesize(text))
    if len(pcm) < SAMPLE_RATE:  # < 0.5 s of audio means something went wrong
        print(f"FAIL: only {len(pcm)} bytes of audio returned")
        return 1
    with wave.open(str(OUT), "wb") as w:
        w.setnchannels(1)
        w.setsampwidth(2)
        w.setframerate(SAMPLE_RATE)
        w.writeframes(pcm)
    seconds = len(pcm) / 2 / SAMPLE_RATE
    words = len(text.split())
    print(f"OK: {OUT.name} written — {seconds:.2f} s audio, first audio after {ttfa} ms, "
          f"{words} words ({words / seconds * 60:.0f} words/min)")
    print(f"Play it:  start {OUT}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
