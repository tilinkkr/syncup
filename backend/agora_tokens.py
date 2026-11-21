"""Session token minting (AccessToken2 / "007", RTC + RTM in one token, 1-hour TTL).

- Worker browser (uid 1001): one token used for both RTC join and RTM login (live transcripts / agent state).
- ConvoAI agent (uid 999999): RTC+RTM token is REQUIRED by Agora when advanced_features.enable_rtm is true.
If AGORA_APP_CERTIFICATE is empty (App-ID-only project) tokens are empty strings.
"""
import settings
from agora_token2 import build_rtc_rtm_token


class TokenConfigError(RuntimeError):
    pass


def _signed() -> bool:
    if not settings.AGORA_APP_ID:
        raise TokenConfigError("AGORA_APP_ID must be set in backend/.env")
    return bool(settings.AGORA_APP_CERTIFICATE)


def build_token(channel_name: str, account: str | int) -> str:
    if not _signed():
        return ""
    return build_rtc_rtm_token(settings.AGORA_APP_ID, settings.AGORA_APP_CERTIFICATE, channel_name,
                               str(account), settings.TOKEN_TTL_SECONDS)


def build_session_tokens(channel_name: str) -> dict:
    user_token = build_token(channel_name, settings.USER_UID)
    return {
        "user_uid": settings.USER_UID,
        "user_rtc_token": user_token,
        "user_rtm_token": user_token,
        "agent_uid": settings.AGENT_UID,
        "agent_rtc_token": build_token(channel_name, settings.AGENT_UID),
    }
