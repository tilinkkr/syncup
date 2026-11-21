"""Environment loading for the SyncUp backend (reads backend/.env)."""
import os
from pathlib import Path

from dotenv import load_dotenv

BASE_DIR = Path(__file__).resolve().parent
load_dotenv(BASE_DIR / ".env")


def _env(name: str, default: str = "") -> str:
    return os.getenv(name, default).strip()


AGORA_APP_ID = _env("AGORA_APP_ID")
AGORA_APP_CERTIFICATE = _env("AGORA_APP_CERTIFICATE")  # empty => project in "App ID only" (testing) mode
AGORA_CUSTOMER_ID = _env("AGORA_CUSTOMER_ID")
AGORA_CUSTOMER_SECRET = _env("AGORA_CUSTOMER_SECRET")

MURF_API_KEY = _env("MURF_API_KEY")
MURF_MODEL = _env("MURF_MODEL", "FALCON")
MURF_BASE_URL = _env("MURF_BASE_URL", "wss://in.api.murf.ai/v1/speech/stream-input")
MURF_VOICES_URL = "https://api.murf.ai/v1/speech/voices"

LLM_CREDENTIAL_MODE = _env("LLM_CREDENTIAL_MODE", "managed")  # managed | byok
LLM_API_URL = _env("LLM_API_URL", "https://api.openai.com/v1/chat/completions")
LLM_API_KEY = _env("LLM_API_KEY")
LLM_MODEL = _env("LLM_MODEL", "gpt-4.1-mini")

PUBLIC_WEBHOOK_BASE_URL = _env("PUBLIC_WEBHOOK_BASE_URL", "http://localhost:8000").rstrip("/")
WEBHOOK_SECRET = _env("WEBHOOK_SECRET")
# Optional: routed work orders are POSTed here (Jira/ERP/Slack bridge). Empty => brief is only logged locally.
OPS_WEBHOOK_URL = _env("OPS_WEBHOOK_URL")
FOLLOW_UP_MINUTES = 30
CORS_ORIGINS = [o for o in _env("CORS_ORIGINS", "http://localhost:3000,http://127.0.0.1:3000").split(",") if o]

USER_UID = 1001
AGENT_UID = 999999  # fixed, non-zero: RTM needs a stable agent identity
TOKEN_TTL_SECONDS = 3600
DEFAULT_LANGUAGE = "ml-IN"
COMPANY_CONTEXT_PATH = BASE_DIR / "data" / "company_context.json"


def missing_for_live_agent() -> list[str]:
    """Names of env vars still required before a real Agora agent can start."""
    required = {
        "AGORA_APP_ID": AGORA_APP_ID,
        "AGORA_CUSTOMER_ID": AGORA_CUSTOMER_ID,
        "AGORA_CUSTOMER_SECRET": AGORA_CUSTOMER_SECRET,
        "MURF_API_KEY": MURF_API_KEY,
    }
    if LLM_CREDENTIAL_MODE == "byok":
        required["LLM_API_KEY"] = LLM_API_KEY
    return [k for k, v in required.items() if not v]


def live_warnings() -> list[str]:
    warnings = []
    if not AGORA_APP_CERTIFICATE:
        warnings.append("AGORA_APP_CERTIFICATE empty: using App-ID-only auth (works only if the project has no certificate enabled)")
    if not PUBLIC_WEBHOOK_BASE_URL.startswith("https://"):
        warnings.append("PUBLIC_WEBHOOK_BASE_URL is not HTTPS: Agora cannot call /tools/* (start ngrok and set it)")
    return warnings
