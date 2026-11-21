from pydantic import BaseModel, Field
from typing import List, Optional, Dict, Any, Literal

# --- /api/config ---
class ConfigTokenRequest(BaseModel):
    channel: str = Field(default="syncup-room-101", description="Agora RTC channel name")
    uid: int = Field(default=100001, description="Numeric User ID for WebRTC client")
    role: int = Field(default=1, description="1 for Publisher, 2 for Subscriber")

class ConfigTokenResponse(BaseModel):
    app_id: str
    channel: str
    user_uid: int
    rtc_token: str
    rtm_token: str
    agent_uid: int
    expires_in: int

# --- /api/agent/start ---
class AgentStartRequest(BaseModel):
    channel: str = Field(default="syncup-room-101", description="Agora RTC channel name")
    user_uid: int = Field(default=100001, description="Numeric User ID that agent interacts with")
    language: str = Field(default="hi-IN", description="Primary language mode ('hi-IN' or 'en-IN')")
    voice_id: Optional[str] = Field(default=None, description="Optional custom Murf voice ID override")

class AgentStartResponse(BaseModel):
    agent_id: str
    status: str
    channel: str
    agent_uid: int
    created_at: int
    tts_voice: str

# --- /api/agent/stop ---
class AgentStopRequest(BaseModel):
    agent_id: Optional[str] = None
    channel: Optional[str] = None

class AgentStopResponse(BaseModel):
    agent_id: str
    status: str
    channel: Optional[str] = None

# --- /tools/triage ---
class TriageRequest(BaseModel):
    session_id: str = Field(default="syncup-room-101")
    statement: str
    category: Literal["fact", "guess", "contradiction"]
    confidence: float = Field(default=0.85, ge=0.0, le=1.0)
    speaker: str = Field(default="worker")
    clarification_prompt: Optional[str] = None

class TriageResponse(BaseModel):
    status: str
    id: str
    statement: str
    category: Literal["fact", "guess", "contradiction"]
    confidence: float
    db_matched: bool
    db_status: Optional[str] = None
    is_contradiction: bool
    contradiction_reason: Optional[str] = None
    clarification_prompt: Optional[str] = None
    execution_time_ms: float

# --- /tools/route ---
class ActionItem(BaseModel):
    task: str
    owner: str = Field(default="Unassigned")
    priority: Literal["low", "medium", "high", "critical"] = Field(default="medium")
    deadline: Optional[str] = None
    status: str = Field(default="Pending")

class RouteTicketRequest(BaseModel):
    session_id: str = Field(default="syncup-room-101")
    title: str = Field(default="Daily Standup Executive Summary")
    summary: Optional[str] = None
    facts: List[str] = Field(default_factory=list)
    guesses: List[str] = Field(default_factory=list)
    contradictions: List[str] = Field(default_factory=list)
    action_items: List[ActionItem] = Field(default_factory=list)
    severity: Literal["low", "medium", "high", "critical"] = Field(default="medium")

class RouteTicketResponse(BaseModel):
    ticket_id: str
    status: str
    routed_at: int
    title: str
    severity: str
    facts_count: int
    unresolved_guesses_count: int
    flagged_contradictions_count: int
    action_items_count: int
    english_brief: str
    destination: str = "Command Center + ERP Synced"
