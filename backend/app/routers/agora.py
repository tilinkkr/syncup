import time
from fastapi import APIRouter, HTTPException, Query
from app.config import settings
from app.models.schemas import (
    ConfigTokenRequest, ConfigTokenResponse,
    AgentStartRequest, AgentStartResponse,
    AgentStopRequest, AgentStopResponse
)
from app.services.agora_client import agora_client
from app.services.rtm_broadcaster import rtm_broadcaster

router = APIRouter(prefix="/api", tags=["Agora Agent & Tokens"])

# Active session agent tracking: channel -> agent_id
ACTIVE_AGENTS = {}

@router.post("/config", response_model=ConfigTokenResponse)
async def generate_config_tokens(request: ConfigTokenRequest):
    """
    Generates short-lived Agora RTC and RTM tokens for the frontend client.
    Audio flows directly via WebRTC SDRTN; data channels flow via RTM.
    """
    rtc_token = agora_client.generate_rtc_token(
        channel=request.channel,
        uid=request.uid,
        role=request.role
    )
    rtm_token = agora_client.generate_rtm_token(
        user_id=str(request.uid)
    )

    return ConfigTokenResponse(
        app_id=settings.AGORA_APP_ID,
        channel=request.channel,
        user_uid=request.uid,
        rtc_token=rtc_token,
        rtm_token=rtm_token,
        agent_uid=settings.AGENT_RTC_UID,
        expires_in=settings.TOKEN_EXPIRATION_SECONDS
    )


@router.post("/agent/start", response_model=AgentStartResponse)
async def start_conversational_agent(request: AgentStartRequest):
    """
    Instructs Agora Conversational AI Engine to spin up an AI Agent
    with built-in ARES ASR ('en-US,hi-IN') and Murf Falcon 2.1 streaming TTS (<100ms TTFA).
    """
    # Guard: check if an agent is already active in this channel
    if request.channel in ACTIVE_AGENTS:
        existing_agent = ACTIVE_AGENTS[request.channel]
        return AgentStartResponse(
            agent_id=existing_agent["agent_id"],
            status="RUNNING (Already Active)",
            channel=request.channel,
            agent_uid=settings.AGENT_RTC_UID,
            created_at=existing_agent["created_at"],
            tts_voice=existing_agent["tts_voice"]
        )

    result = await agora_client.join_agent(
        channel=request.channel,
        user_uid=request.user_uid,
        voice_id=request.voice_id,
        language=request.language
    )

    agent_record = {
        "agent_id": result["agent_id"],
        "status": result["status"],
        "channel": request.channel,
        "created_at": int(time.time()),
        "tts_voice": result.get("tts_voice", settings.MURF_DEFAULT_VOICE_ID)
    }
    ACTIVE_AGENTS[request.channel] = agent_record

    # Broadcast agent state event
    rtm_broadcaster.broadcast_event(
        channel=request.channel,
        event_type="agent_state",
        payload={
            "state": "active",
            "agent_id": result["agent_id"],
            "tts_voice": agent_record["tts_voice"],
            "status": "ready"
        }
    )

    return AgentStartResponse(
        agent_id=result["agent_id"],
        status=result["status"],
        channel=request.channel,
        agent_uid=settings.AGENT_RTC_UID,
        created_at=agent_record["created_at"],
        tts_voice=agent_record["tts_voice"]
    )


@router.post("/agent/stop", response_model=AgentStopResponse)
async def stop_conversational_agent(request: AgentStopRequest):
    """
    Terminates the Agora Conversational AI agent and disconnects it from the WebRTC channel.
    """
    target_channel = request.channel
    target_agent_id = request.agent_id

    if not target_agent_id and target_channel and target_channel in ACTIVE_AGENTS:
        target_agent_id = ACTIVE_AGENTS[target_channel]["agent_id"]

    if not target_agent_id:
        target_agent_id = "agent_unknown"

    result = await agora_client.stop_agent(target_agent_id)

    if target_channel and target_channel in ACTIVE_AGENTS:
        del ACTIVE_AGENTS[target_channel]
        rtm_broadcaster.broadcast_event(
            channel=target_channel,
            event_type="agent_state",
            payload={"state": "idle", "agent_id": target_agent_id, "status": "stopped"}
        )

    return AgentStopResponse(
        agent_id=target_agent_id,
        status="STOPPED",
        channel=target_channel
    )


@router.get("/agent/status/{channel}")
async def get_agent_status(channel: str):
    """
    Returns the real-time operational status of an active agent in a given channel.
    """
    agent = ACTIVE_AGENTS.get(channel)
    if not agent:
        return {"channel": channel, "is_active": False, "status": "IDLE"}
    return {
        "channel": channel,
        "is_active": True,
        "agent_id": agent["agent_id"],
        "status": agent["status"],
        "created_at": agent["created_at"],
        "tts_voice": agent["tts_voice"]
    }


@router.get("/events/{channel}")
async def get_recent_events(channel: str, since: int = Query(default=0)):
    """
    Returns real-time events for the frontend Command Center.
    """
    return {
        "channel": channel,
        "events": rtm_broadcaster.get_events_since(channel, last_timestamp=since)
    }
