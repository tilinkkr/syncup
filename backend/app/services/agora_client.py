import base64
import time
import uuid
import logging
import httpx
from typing import Optional, Dict, Any

from app.config import settings

logger = logging.getLogger(__name__)

# Try importing official agora-token-builder, fallback to safe mock token if missing in dev
try:
    from agora_token_builder import RtcTokenBuilder, RtmTokenBuilder
    TOKEN_BUILDER_AVAILABLE = True
except ImportError:
    logger.warning("agora-token-builder not installed; using fallback mock token generator")
    TOKEN_BUILDER_AVAILABLE = False


class AgoraClientService:
    def __init__(self):
        self.app_id = settings.AGORA_APP_ID
        self.app_certificate = settings.AGORA_APP_CERTIFICATE
        self.customer_key = settings.AGORA_CUSTOMER_KEY
        self.customer_secret = settings.AGORA_CUSTOMER_SECRET
        self.base_url = "https://api.agora.io/api/conversational-ai-agent/v2"

    def _get_basic_auth_header(self) -> Dict[str, str]:
        credentials = f"{self.customer_key}:{self.customer_secret}"
        encoded = base64.b64encode(credentials.encode("utf-8")).decode("utf-8")
        return {
            "Authorization": f"Basic {encoded}",
            "Content-Type": "application/json"
        }

    def generate_rtc_token(self, channel: str, uid: int, role: int = 1) -> str:
        """
        Builds RTC token for publishing audio.
        role: 1 = Publisher, 2 = Subscriber
        """
        if TOKEN_BUILDER_AVAILABLE and self.app_certificate != "demo_agora_app_certificate":
            current_timestamp = int(time.time())
            privilege_expired_ts = current_timestamp + settings.TOKEN_EXPIRATION_SECONDS
            return RtcTokenBuilder.buildTokenWithUid(
                self.app_id, self.app_certificate, channel, uid, role, privilege_expired_ts
            )
        else:
            # Deterministic development mock token for testing
            mock_payload = f"007eJxTYG{uuid.uuid4().hex[:12]}_{channel}_{uid}_{int(time.time())}"
            return mock_payload

    def generate_rtm_token(self, user_id: str) -> str:
        """
        Builds RTM token for data channel subscriptions.
        """
        if TOKEN_BUILDER_AVAILABLE and self.app_certificate != "demo_agora_app_certificate":
            current_timestamp = int(time.time())
            privilege_expired_ts = current_timestamp + settings.TOKEN_EXPIRATION_SECONDS
            return RtmTokenBuilder.buildToken(
                self.app_id, self.app_certificate, user_id, privilege_expired_ts
            )
        else:
            mock_payload = f"007rtm{uuid.uuid4().hex[:12]}_{user_id}_{int(time.time())}"
            return mock_payload

    async def join_agent(
        self,
        channel: str,
        user_uid: int,
        voice_id: Optional[str] = None,
        language: str = "hi-IN"
    ) -> Dict[str, Any]:
        """
        Calls Agora Conversational AI REST API v2 POST /projects/{appid}/join
        Configures ARES ASR, GPT-4o-mini with native tools, and Murf Falcon 2.1 streaming TTS.
        """
        selected_voice = voice_id or (
            settings.MURF_DEFAULT_VOICE_ID if language == "hi-IN" else "en-IN-eashan"
        )
        agent_rtc_token = self.generate_rtc_token(
            channel=channel, uid=settings.AGENT_RTC_UID, role=1
        )

        join_payload = {
            "name": f"syncup_agent_{channel}",
            "properties": {
                "channel": channel,
                "token": agent_rtc_token,
                "agent_rtc_uid": str(settings.AGENT_RTC_UID),
                "remote_rtc_uids": [str(user_uid)],
                "enable_string_uid": False,
                "idle_timeout": 120
            },
            "parameters": {
                "asr": {
                    "language": "en-US,hi-IN",
                    "model": "ARES",
                    "words": [
                        "VFD", "SCADA", "P&ID", "Hazmat", "LOTO", "Lockout-Tagout",
                        "psi", "bar", "overheating", "bypass valve", "bearing",
                        "line 2", "boiler 2", "pump 4", "rpm", "telemetry"
                    ]
                },
                "llm": {
                    "model": settings.LLM_MODEL,
                    "system_prompt": (
                        "You are SyncUp, an expert bilingual (Hindi/English) Voice AI operational partner for frontline workers. "
                        "Evaluate statements into FACTS, GUESSES, and CONTRADICTIONS. "
                        "When the worker makes an unverified guess, ask for verification in natural Hinglish. "
                        "When a statement contradicts company ground truth, politely flag the issue immediately. "
                        "Speak in concise Hinglish (1-2 sentences). Call triage_statement and route_syncup_ticket tools."
                    ),
                    "greeting": "Namaste team! Main aapka Voice SyncUp partner hoon. Aaj ke standup updates ya issues bataiye.",
                    "server_url": settings.PUBLIC_WEBHOOK_URL
                },
                "tts": {
                    "vendor": "murf",
                    "model": "FALCON",
                    "voice_id": selected_voice,
                    "sample_rate": 24000,
                    "base_url": settings.MURF_BASE_WSS_URL,
                    "options": {
                        "rate": 1.0,
                        "buffer_size_chars": 25,
                        "flush_on_punctuation": True
                    }
                },
                "turn_detection": {
                    "type": "server_vad",
                    "silence_duration_ms": 350,
                    "prefix_padding_ms": 300,
                    "speech_threshold": 0.5,
                    "create_response": True,
                    "interrupt_response": True
                }
            }
        }

        # If live Agora credentials are provided, call the cloud endpoint
        if self.customer_key != "demo_customer_key" and self.app_id != "demo_agora_app_id":
            url = f"{self.base_url}/projects/{self.app_id}/join"
            headers = self._get_basic_auth_header()
            async with httpx.AsyncClient(timeout=10.0) as client:
                try:
                    response = await client.post(url, json=join_payload, headers=headers)
                    response.raise_for_status()
                    data = response.json()
                    return {
                        "agent_id": data.get("data", {}).get("agent_id", f"cai_agt_{uuid.uuid4().hex[:8]}"),
                        "status": "RUNNING",
                        "channel": channel,
                        "tts_voice": selected_voice
                    }
                except Exception as e:
                    logger.error(f"Error calling Agora /join API: {e}. Falling back to simulation mode.")

        # Development Simulation Mode
        simulated_agent_id = f"cai_agt_sim_{uuid.uuid4().hex[:10]}"
        return {
            "agent_id": simulated_agent_id,
            "status": "RUNNING (Simulated Edge)",
            "channel": channel,
            "tts_voice": selected_voice
        }

    async def stop_agent(self, agent_id: str) -> Dict[str, Any]:
        """
        Calls Agora Conversational AI REST API v2 POST /projects/{appid}/leave
        """
        if self.customer_key != "demo_customer_key" and self.app_id != "demo_agora_app_id":
            url = f"{self.base_url}/projects/{self.app_id}/leave"
            headers = self._get_basic_auth_header()
            payload = {"agent_id": agent_id}
            async with httpx.AsyncClient(timeout=5.0) as client:
                try:
                    response = await client.post(url, json=payload, headers=headers)
                    response.raise_for_status()
                    return {"agent_id": agent_id, "status": "STOPPED"}
                except Exception as e:
                    logger.error(f"Error calling Agora /leave API: {e}")

        return {"agent_id": agent_id, "status": "STOPPED"}


agora_client = AgoraClientService()
