from fastapi import APIRouter, BackgroundTasks, HTTPException
from typing import Dict, Any

from app.models.schemas import (
    TriageRequest, TriageResponse,
    RouteTicketRequest, RouteTicketResponse
)
from app.services.epistemic_service import epistemic_service
from app.services.rtm_broadcaster import rtm_broadcaster

router = APIRouter(prefix="/tools", tags=["Epistemic Tools & Webhooks"])


@router.post("/triage", response_model=TriageResponse)
async def triage_statement(payload: TriageRequest, background_tasks: BackgroundTasks):
    """
    Webhook called by Agora Conversational AI Engine's LLM orchestrator.
    Evaluates worker utterance against company ground truth database in <150ms.
    Broadcasts state updates to the Frontend Command Center.
    """
    result = epistemic_service.evaluate_statement(
        session_id=payload.session_id,
        statement=payload.statement,
        provided_category=payload.category,
        confidence=payload.confidence
    )

    # Asynchronously push event to Frontend Command Center via RTM broadcaster
    background_tasks.add_task(
        rtm_broadcaster.broadcast_event,
        channel=payload.session_id,
        event_type="triage",
        payload=result.model_dump()
    )

    # Also broadcast transcript event
    background_tasks.add_task(
        rtm_broadcaster.broadcast_event,
        channel=payload.session_id,
        event_type="transcript",
        payload={
            "speaker": payload.speaker,
            "text": payload.statement,
            "category": result.category,
            "is_contradiction": result.is_contradiction
        }
    )

    return result


@router.post("/route", response_model=RouteTicketResponse)
async def route_syncup_ticket(payload: RouteTicketRequest, background_tasks: BackgroundTasks):
    """
    Webhook called by Agora Conversational AI Engine when sync-up is concluding.
    Compiles confirmed Facts, unverified Guesses, and resolved Contradictions into an English ticket.
    """
    result = epistemic_service.route_ticket(payload)

    # Broadcast executive ticket event to UI
    background_tasks.add_task(
        rtm_broadcaster.broadcast_event,
        channel=payload.session_id,
        event_type="ticket",
        payload=result.model_dump()
    )

    return result


@router.get("/context")
async def get_company_context():
    """
    Returns the active plant operational ground truth (equipment states, shift roster, safety alerts).
    """
    return epistemic_service.ground_truth.model_dump()


@router.get("/session/{session_id}")
async def get_session_summary(session_id: str):
    """
    Returns all tracked facts, guesses, and contradictions for an active session.
    """
    session = epistemic_service._get_or_create_session(session_id)
    return {
        "session_id": session_id,
        "facts_count": len(session.get("facts", [])),
        "guesses_count": len(session.get("guesses", [])),
        "contradictions_count": len(session.get("contradictions", [])),
        "facts": session.get("facts", []),
        "guesses": session.get("guesses", []),
        "contradictions": session.get("contradictions", [])
    }
