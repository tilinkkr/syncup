from pydantic_settings import BaseSettings, SettingsConfigDict
from typing import List
import os

class Settings(BaseSettings):
    # Agora Configuration
    AGORA_APP_ID: str = "demo_agora_app_id"
    AGORA_APP_CERTIFICATE: str = "demo_agora_app_certificate"
    AGORA_CUSTOMER_KEY: str = "demo_customer_key"
    AGORA_CUSTOMER_SECRET: str = "demo_customer_secret"
    
    # Murf.ai Configuration (Falcon 2.1 Streaming TTS)
    MURF_API_KEY: str = "demo_murf_api_key"
    MURF_DEFAULT_VOICE_ID: str = "hi-IN-kabir"
    MURF_BASE_WSS_URL: str = "wss://in.api.murf.ai/v1/speech/stream-input"
    
    # LLM / OpenAI Configuration (Orchestrated by Agora ConvoAI)
    OPENAI_API_KEY: str = "demo_openai_api_key"
    LLM_MODEL: str = "gpt-4o-mini"
    
    # Service Network Settings
    BACKEND_HOST: str = "0.0.0.0"
    BACKEND_PORT: int = 8000
    ENVIRONMENT: str = "development"
    CORS_ORIGINS: str = "http://localhost:3000,http://127.0.0.1:3000,*"
    
    # Public URL where Agora ConvoAI calls /tools webhooks
    PUBLIC_WEBHOOK_URL: str = "http://localhost:8000/tools"
    
    # Token Settings
    TOKEN_EXPIRATION_SECONDS: int = 86400
    AGENT_RTC_UID: int = 999999
    
    model_config = SettingsConfigDict(
        env_file=os.path.join(os.path.dirname(os.path.dirname(__file__)), "..", ".env"),
        env_file_encoding="utf-8",
        extra="ignore"
    )

    @property
    def cors_origins_list(self) -> List[str]:
        return [origin.strip() for origin in self.CORS_ORIGINS.split(",") if origin.strip()]

settings = Settings()
