import re
import uuid
import time
import logging
from typing import Dict, Any, List, Optional
from app.models.company_context import INITIAL_GROUND_TRUTH, GroundTruthDB
from app.models.schemas import TriageResponse, RouteTicketRequest, RouteTicketResponse, ActionItem

logger = logging.getLogger(__name__)

class EpistemicService:
    def __init__(self):
        self.ground_truth: GroundTruthDB = INITIAL_GROUND_TRUTH
        # Active session state memory: session_id -> {facts: [], guesses: [], contradictions: []}
        self.session_memory: Dict[str, Dict[str, List[Any]]] = {}

    def _get_or_create_session(self, session_id: str) -> Dict[str, List[Any]]:
        if session_id not in self.session_memory:
            self.session_memory[session_id] = {
                "facts": [],
                "guesses": [],
                "contradictions": [],
                "history": []
            }
        return self.session_memory[session_id]

    def evaluate_statement(
        self,
        session_id: str,
        statement: str,
        provided_category: Optional[str] = None,
        confidence: float = 0.85
    ) -> TriageResponse:
        start_time = time.perf_counter()
        normalized_text = statement.lower()
        session = self._get_or_create_session(session_id)
        statement_id = f"tri_{uuid.uuid4().hex[:8]}"

        db_matched = False
        db_status = None
        is_contradiction = False
        contradiction_reason = None
        final_category = provided_category or "fact"
        clarification_prompt = None

        # -------------------------------------------------------------
        # 1. CONTRADICTION DETECTION ENGINE (Checks Against Ground Truth)
        # -------------------------------------------------------------
        
        # Check: Line 2 (Bottling & Packaging Line 2)
        if "line 2" in normalized_text or "line-02" in normalized_text:
            db_matched = True
            line_state = self.ground_truth.equipment.get("LINE-02")
            if any(term in normalized_text for term in ["chalu", "running", "started", "on kar di", "shuru", "operational"]):
                if line_state and line_state.locked_out:
                    is_contradiction = True
                    final_category = "contradiction"
                    contradiction_reason = (
                        "Line 2 is under mandatory Lockout-Tagout (WO-4482) until 14:00 IST for conveyor motor rewiring. "
                        "Power grid is isolated."
                    )
                    clarification_prompt = (
                        "Maintenance records ke mutabiq Line 2 Lockout-Tagout par hai. "
                        "Kya kisi ne safety override enable kiya hai ya maintenance team se clearance mili hai?"
                    )
            elif any(term in normalized_text for term in ["shutdown", "loto", "stopped", "band"]):
                final_category = "fact"
                db_status = "Consistent with Line 2 LOTO safety hold record."

        # Check: Pump 4 (Auxiliary Coolant Pump)
        elif "pump 4" in normalized_text or "pump-04" in normalized_text:
            db_matched = True
            pump_state = self.ground_truth.equipment.get("PUMP-04")
            if any(term in normalized_text for term in ["chalu", "running", "on hai", "operating"]):
                if pump_state and pump_state.status == "OFFLINE":
                    is_contradiction = True
                    final_category = "contradiction"
                    contradiction_reason = "Pump 4 is OFFLINE awaiting spare mechanical seal replacement from vendor."
                    clarification_prompt = (
                        "Telemetry show karti hai Pump 4 offline hai (0 RPM). "
                        "Aap kaunse pump ki baat kar rahe hain?"
                    )
            else:
                db_status = f"Pump 4 telemetry confirms 0 RPM (Status: {pump_state.status})."

        # Check: Boiler 2 (High-Pressure Steam Boiler #2)
        elif "boiler" in normalized_text or "boiler 2" in normalized_text or "boiler-02" in normalized_text:
            db_matched = True
            boiler_state = self.ground_truth.equipment.get("BOILER-02")
            telemetry = boiler_state.telemetry if boiler_state else {}
            current_bar = telemetry.get("pressure_bar", 4.1)

            if any(term in normalized_text for term in ["pressure drop", "fluctuat", "leak", "kharab", "failure"]):
                # Worker reports a problem; is it confirmed or a guess?
                if any(guess_word in normalized_text for guess_word in ["lagta", "shayad", "maybe", "hoga", "suspect", "might"]):
                    final_category = "guess"
                    db_status = f"Current SCADA telemetry: Nominal {current_bar} bar / 182°C."
                    clarification_prompt = (
                        f"SCADA telemetry nominal {current_bar} bar dikha rahi hai. "
                        "Aapne kya physical leak dekha hai ya acoustic vibration notice ki?"
                    )
                else:
                    final_category = "fact"
                    db_status = f"Reported field observation noted against Boiler 2 telemetry ({current_bar} bar)."
            else:
                final_category = "fact"
                db_status = f"Boiler 2 operating nominally at {current_bar} bar."

        # Check: Coolant Tank
        elif "coolant" in normalized_text or "tank" in normalized_text:
            db_matched = True
            tank_state = self.ground_truth.equipment.get("COOLANT-TANK-03")
            level = tank_state.telemetry.get("fill_level_percent", 85.0) if tank_state else 85.0
            db_status = f"Coolant reserve at {level}% capacity."
            final_category = "fact"

        # -------------------------------------------------------------
        # 2. GUESS DETECTION HEURISTICS (Linguistic markers)
        # -------------------------------------------------------------
        if not is_contradiction:
            guess_patterns = [
                r"\blagta\b", r"\bshayad\b", r"\bmaybe\b", r"\bprobably\b",
                r"\bsuspect\b", r"\bguess\b", r"\bhoga\b", r"\blag raha\b",
                r"\bmight be\b", r"\bcould be\b", r"\bunclear\b"
            ]
            if any(re.search(pat, normalized_text) for pat in guess_patterns):
                final_category = "guess"
                if not clarification_prompt:
                    clarification_prompt = (
                        "Aapne yeh observation kis basis par note ki? "
                        "Kya iska koi physical measurement ya instrument reading hai?"
                    )

        # -------------------------------------------------------------
        # 3. RECORD IN SESSION MEMORY
        # -------------------------------------------------------------
        record_entry = {
            "id": statement_id,
            "statement": statement,
            "category": final_category,
            "confidence": confidence,
            "is_contradiction": is_contradiction,
            "contradiction_reason": contradiction_reason,
            "db_status": db_status,
            "timestamp": int(time.time())
        }

        if final_category == "fact":
            session["facts"].append(record_entry)
        elif final_category == "guess":
            session["guesses"].append(record_entry)
        elif final_category == "contradiction":
            session["contradictions"].append(record_entry)
        session["history"].append(record_entry)

        elapsed_ms = (time.perf_counter() - start_time) * 1000

        return TriageResponse(
            status="success",
            id=statement_id,
            statement=statement,
            category=final_category,
            confidence=confidence,
            db_matched=db_matched,
            db_status=db_status,
            is_contradiction=is_contradiction,
            contradiction_reason=contradiction_reason,
            clarification_prompt=clarification_prompt,
            execution_time_ms=round(elapsed_ms, 2)
        )

    def route_ticket(self, request: RouteTicketRequest) -> RouteTicketResponse:
        session = self._get_or_create_session(request.session_id)
        ticket_id = f"TICK-{int(time.time()) % 100000:05d}"
        
        # Combine explicitly passed facts/guesses with internal session memory
        all_facts = list(dict.fromkeys(
            request.facts + [f["statement"] for f in session.get("facts", [])]
        ))
        all_guesses = list(dict.fromkeys(
            request.guesses + [g["statement"] for g in session.get("guesses", [])]
        ))
        all_contradictions = list(dict.fromkeys(
            request.contradictions + [
                f"{c['statement']} [REFUTED: {c.get('contradiction_reason', 'Conflict with DB')}]"
                for c in session.get("contradictions", [])
            ]
        ))

        # Default action items if none provided
        action_items = request.action_items
        if not action_items:
            if all_guesses:
                action_items.append(ActionItem(
                    task=f"Conduct physical inspection to verify: '{all_guesses[0]}'",
                    owner="Assigned Field Engineer",
                    priority="high",
                    deadline="Within 2 hours"
                ))
            if all_contradictions:
                action_items.append(ActionItem(
                    task="Audit safety lockout tags on Line 2 breaker panel",
                    owner=self.ground_truth.roster.supervisor,
                    priority="critical",
                    deadline="Immediate"
                ))

        # Generate English Markdown Brief
        brief_markdown = (
            f"# 📋 EXECUTIVE SYNCUP BRIEF: {ticket_id}\n"
            f"**Station:** {self.ground_truth.plant_name} | **Supervisor:** {self.ground_truth.roster.supervisor}\n"
            f"**Shift:** {self.ground_truth.roster.shift_name} | **Severity:** {request.severity.upper()}\n\n"
            f"### 🟢 Verified Operational Facts ({len(all_facts)})\n"
        )
        if all_facts:
            for i, f in enumerate(all_facts, 1):
                brief_markdown += f"{i}. {f}\n"
        else:
            brief_markdown += "_No standalone facts recorded._\n"

        brief_markdown += f"\n### 🟡 Unverified Speculations Requiring Inspection ({len(all_guesses)})\n"
        if all_guesses:
            for i, g in enumerate(all_guesses, 1):
                brief_markdown += f"{i}. {g}\n"
        else:
            brief_markdown += "_None. All updates grounded in telemetry or direct observation._\n"

        brief_markdown += f"\n### 🔴 Debunked Contradictions / Safety Mismatches ({len(all_contradictions)})\n"
        if all_contradictions:
            for i, c in enumerate(all_contradictions, 1):
                brief_markdown += f"{i}. {c}\n"
        else:
            brief_markdown += "_Zero safety or telemetry contradictions flagged._\n"

        brief_markdown += "\n### ⚡ Assigned Action Items\n"
        brief_markdown += "| Task | Owner | Priority | Deadline |\n| :--- | :--- | :--- | :--- |\n"
        for item in action_items:
            brief_markdown += f"| {item.task} | {item.owner} | {item.priority.upper()} | {item.deadline or 'TBD'} |\n"

        return RouteTicketResponse(
            ticket_id=ticket_id,
            status="routed",
            routed_at=int(time.time()),
            title=request.title,
            severity=request.severity,
            facts_count=len(all_facts),
            unresolved_guesses_count=len(all_guesses),
            flagged_contradictions_count=len(all_contradictions),
            action_items_count=len(action_items),
            english_brief=brief_markdown
        )

epistemic_service = EpistemicService()
