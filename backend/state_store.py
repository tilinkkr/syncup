"""In-memory, asyncio-safe epistemic state per channel with SSE fan-out."""
import asyncio
import copy
import itertools
import time
from datetime import datetime
from typing import Any

MAX_LOGS = 300
_log_seq = itertools.count(1)

# BEFORE_CONTEXT -> INVESTIGATING -> AWAITING_APPROVAL -> ROUTED, plus ERROR_HANDLED (graceful failure, recoverable)
STATUSES = ("BEFORE_CONTEXT", "INVESTIGATING", "AWAITING_APPROVAL", "ROUTED", "ERROR_HANDLED")


def _blank(channel: str) -> dict[str, Any]:
    return {
        "channel": channel,
        "agent_id": None,
        "status": "BEFORE_CONTEXT",
        "asset_id": None,
        "verified_facts": [],
        "unverified_guesses": [],
        "debunked_claims": [],
        "missing_unknowns": [],
        "english_brief": None,
        "asset_context": None,  # BEFORE: maintenance history pre-loaded (QR scan / scenario) before the call
        "proposed_ticket": None,  # CONFIRM: drafted work order awaiting the worker's approval
        "confirmation_question": None,  # the spoken approval question, in the worker's language
        "approval": None,  # {"via": "voice" | "manual", "at": ts}
        "follow_up_schedule": None,
        "escalation": None,
        # Presentation flow: QR_READY -> WORKER_CALL -> ENGINEER_RINGING -> ENGINEER_CONNECTED -> DISPATCH_CONFIRMED
        "demo_stage": "QR_READY",
        "engineer_brief": None,  # AFTER: outbound English call to the on-call engineer
        "worker_name": None,  # AFTER: automated voice check-in
        "error": None,
        "language": None,
        "asset_hint": None,
        "active_check": None,
        "environment": None,
        "simulated": False,
        "transcripts": [],
        "logs": [],
        "updated_at": time.time(),
    }


class StateStore:
    def __init__(self) -> None:
        self._states: dict[str, dict[str, Any]] = {}
        # Every Agora agent we started and have not yet stopped: agent_id -> {channel, kind, started_at}.
        # Used to guarantee that no two agents ever talk at once (zombie teardown before each /join).
        self.active_agents: dict[str, dict[str, Any]] = {}
        self._subscribers: dict[str, list[asyncio.Queue]] = {}
        self._lock = asyncio.Lock()

    async def get(self, channel: str) -> dict[str, Any]:
        async with self._lock:
            return copy.deepcopy(self._states.get(channel) or _blank(channel))

    async def reset(self, channel: str, status: str = "BEFORE_CONTEXT", agent_id: str | None = None,
                    **fields: Any) -> dict[str, Any]:
        state = _blank(channel)
        state.update(status=status, agent_id=agent_id, **fields)
        return await self._commit(channel, state)

    async def update(self, channel: str, mutator) -> dict[str, Any]:
        """Apply `mutator(state)` atomically, then broadcast the new snapshot."""
        async with self._lock:
            state = self._states.get(channel) or _blank(channel)
            mutator(state)
            state["updated_at"] = time.time()
            self._states[channel] = state
            snapshot = copy.deepcopy(state)
        self._publish(channel, snapshot)
        return snapshot

    async def _commit(self, channel: str, state: dict[str, Any]) -> dict[str, Any]:
        async with self._lock:
            self._states[channel] = state
            snapshot = copy.deepcopy(state)
        self._publish(channel, snapshot)
        return snapshot

    def register_agent(self, agent_id: str, channel: str, kind: str) -> None:
        self.active_agents[agent_id] = {"channel": channel, "kind": kind, "started_at": time.time()}

    def unregister_agent(self, agent_id: str | None) -> None:
        if agent_id:
            self.active_agents.pop(agent_id, None)

    def agents(self, kind: str | None = None) -> list[tuple[str, dict[str, Any]]]:
        return [(a, m) for a, m in self.active_agents.items() if kind is None or m["kind"] == kind]

    @staticmethod
    def make_log(level: str, source: str, message: str) -> dict[str, Any]:
        """level: INFO | WARN | ACTION; source: RTC | ASR | TTS | TRIAGE | DB | ROUTE"""
        return {"id": f"log-{next(_log_seq)}", "ts": datetime.now().strftime("%H:%M:%S.%f")[:-3],
                "level": level, "source": source, "message": message}

    @staticmethod
    def append_logs(state: dict[str, Any], entries: list[dict[str, Any]]) -> None:
        state.setdefault("logs", []).extend(entries)
        del state["logs"][:-MAX_LOGS]

    async def log(self, channel: str, level: str, source: str, message: str) -> dict[str, Any]:
        entry = self.make_log(level, source, message)
        return await self.update(channel, lambda s: self.append_logs(s, [entry]))

    def subscribe(self, channel: str) -> asyncio.Queue:
        q: asyncio.Queue = asyncio.Queue(maxsize=100)
        self._subscribers.setdefault(channel, []).append(q)
        return q

    def unsubscribe(self, channel: str, q: asyncio.Queue) -> None:
        subs = self._subscribers.get(channel, [])
        if q in subs:
            subs.remove(q)

    def _publish(self, channel: str, snapshot: dict[str, Any]) -> None:
        for q in list(self._subscribers.get(channel, [])):
            if q.full():  # slow consumer: drop oldest, keep latest state
                try:
                    q.get_nowait()
                except asyncio.QueueEmpty:
                    pass
            q.put_nowait(snapshot)


store = StateStore()
