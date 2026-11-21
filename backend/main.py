"""Multilingual Voice SyncUp — FastAPI backend (Milestone 4: HITL approval + per-language prosody).

Run:  backend\\.venv\\Scripts\\python.exe -m uvicorn main:app --app-dir backend --port 8000
Audio never touches this service: it mints tokens, drives the Agora ConvoAI agent lifecycle, serves the
LLM tool webhooks, and streams the live epistemic state (SSE). Triage/route logic lives in run_triage /
run_route so the webhook path and the stage Demo Sim execute exactly the same code.
"""
import asyncio
import base64
import contextlib
import itertools
import json
import logging
import time
from typing import Any

import httpx
from fastapi import FastAPI, Header, HTTPException, Query, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import StreamingResponse
from pydantic import BaseModel

import agora_convo
import agora_tokens
import epistemic
import phonetics
import settings
import speech_normalizer
from state_store import store

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(name)s: %(message)s")
log = logging.getLogger("syncup")


@contextlib.asynccontextmanager
async def lifespan(_app: FastAPI):
    voices = await agora_convo.resolve_murf_voices()
    asyncio.get_running_loop().create_task(preflight())  # warm DNS/TLS so the UI's first preflight is fast
    if voices:
        log.info("Murf Falcon voices validated: %s", voices)
    for w in settings.live_warnings():
        log.warning(w)
    yield


app = FastAPI(title="Multilingual Voice SyncUp", version="3.0.0", lifespan=lifespan)
app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.CORS_ORIGINS,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

_ticket_seq = itertools.count(104)
L = store.make_log  # shorthand: L(level, source, message)


# ----------------------------------------------------------------------------- models
class SessionStartRequest(BaseModel):
    channel_name: str = "auto"  # "auto"/"" -> a fresh unique channel per call (never reuse a channel)
    previous_channel: str | None = None  # carry the QR-scanned context over from the lobby channel
    language: str = settings.DEFAULT_LANGUAGE
    asset_hint: str = "LINE-03"
    environment: str = agora_convo.DEFAULT_ENVIRONMENT


class SessionStopRequest(BaseModel):
    channel_name: str
    agent_id: str | None = None


# ----------------------------------------------------------------------------- helpers
def _check_webhook_secret(key: str | None) -> None:
    if settings.WEBHOOK_SECRET and key != settings.WEBHOOK_SECRET:
        raise HTTPException(401, "invalid X-SyncUp-Key")


async def _tool_args(request: Request) -> dict[str, Any]:
    """Accept raw args, or OpenAI/Agora-style wrappers ({"arguments": "...json..."})."""
    try:
        body = await request.json()
    except Exception:
        body = {}
    if not isinstance(body, dict):
        return {}
    for key in ("arguments", "args", "parameters"):
        inner = body.get(key)
        if isinstance(inner, str):
            try:
                inner = json.loads(inner)
            except json.JSONDecodeError:
                inner = None
        if isinstance(inner, dict):
            return {**body, **inner}
    return body


def _channel(query_channel: str | None, args: dict) -> str:
    ch = query_channel or args.get("channel") or args.get("channel_name")
    if not ch:
        raise HTTPException(400, "channel is required (query ?channel= or body)")
    return ch


def _as_list(value: Any) -> list[str]:
    if value is None:
        return []
    if isinstance(value, str):
        return [value] if value.strip() else []
    return [str(v).strip() for v in value if str(v).strip()]


def _texts(items: list[dict]) -> set[str]:
    return {i["text"].lower() for i in items}


def _question(rule: dict) -> str:
    q = rule["check_question"]
    return q[len("Ask if "):] if q.startswith("Ask if ") else q


# ----------------------------------------------------------------------------- core epistemic engine
async def run_triage(ch: str, args: dict[str, Any]) -> dict[str, Any]:
    t0 = time.perf_counter()
    facts = _as_list(args.get("verified_facts"))
    guesses = _as_list(args.get("worker_guesses"))
    unknowns = _as_list(args.get("missing_unknowns"))
    asset_id = epistemic.resolve_asset(args.get("asset_id"), facts + guesses + unknowns)
    sop_code, sop = epistemic.pick_sop(asset_id, args.get("fault_code"), facts + unknowns)

    debunked, still_guesses = [], []
    for g in guesses:
        hit = epistemic.find_contradiction(asset_id, g)
        if hit:
            debunked.append({"text": g, "log_id": hit["log_id"], "evidence": epistemic.evidence_string(hit),
                             "component": hit["component"], "status": hit["status"], "date": hit["date"]})
        else:
            still_guesses.append({"text": g, "asset_id": asset_id})

    # < 30-token directive for the LLM to voice next.
    # Short, human directive for the LLM: describe records in plain words, never read their IDs aloud.
    if debunked and sop:
        d = debunked[0]
        directive = (f"Kindly say it was a fair thought, but the maintenance record shows the {d['component'].lower()} "
                     f"is {phonetics.natural_status(d['status'])} ({d['date']}). Then ask if {_question(sop)}.")
    elif sop:
        directive = f"Calmly ask the worker if {_question(sop)}."
    elif unknowns:
        directive = f"Kindly ask the worker to check: {unknowns[0]}."
    else:
        directive = "Kindly ask which machine it is and what exactly they saw."
    active_check = {"sop_code": sop_code, "question": _question(sop) if sop else (unknowns[0] if unknowns else None),
                    "directive": directive}

    new_logs = [L("INFO", "TRIAGE",
                  f"Extracted {len(facts)} fact{'s' * (len(facts) != 1)}, {len(guesses)} guess"
                  f"{'es' * (len(guesses) != 1)}, {len(unknowns)} unknown | asset {asset_id or '?'} "
                  f"| Checking company_context.json...")]
    for d in debunked:
        new_logs.append(L("ACTION", "DB", f"DEBUNKED: '{d['text']}' contradicted by {d['log_id']}"
                                          f" ({d['evidence'].split(': ', 1)[-1]})"))
    for g in still_guesses:
        new_logs.append(L("WARN", "DB", f"UNVERIFIED: '{g['text']}' - no matching record, needs physical check"))
    if sop:
        new_logs.append(L("INFO", "DB", f"SOP {sop_code} matched: {sop['fault']}"))

    def _apply(s: dict) -> None:
        store.append_logs(s, new_logs)
        if s["status"] in ("BEFORE_CONTEXT", "ERROR_HANDLED"):
            s["status"] = "INVESTIGATING"
            s["error"] = None
        if asset_id:
            s["asset_id"] = asset_id
        if sop_code:
            s["sop_code"] = sop_code
        for f in facts:
            if f.lower() not in _texts(s["verified_facts"]):
                s["verified_facts"].append({"text": f, "source": "worker"})
        debunked_texts = {d["text"].lower() for d in debunked}
        for d in debunked:
            if d["text"].lower() not in _texts(s["debunked_claims"]):
                s["debunked_claims"].append(d)
        s["unverified_guesses"] = [g for g in s["unverified_guesses"] if g["text"].lower() not in debunked_texts]
        for g in still_guesses:
            if g["text"].lower() not in _texts(s["unverified_guesses"]):
                s["unverified_guesses"].append(g)
        for u in unknowns:
            if u.lower() not in _texts(s["missing_unknowns"]):
                s["missing_unknowns"].append({"text": u})
        s["active_check"] = active_check

    snap = await store.update(ch, _apply)
    result = {"status": "recorded", "asset_id": asset_id, "db_matched": bool(debunked), "debunked": debunked,
              "directive": directive}
    lang = _phonetic_lang(snap)
    if lang and sop_code and any(c.isdigit() for c in sop_code):  # only the error code is ever said aloud
        spoken = phonetics.speak(sop_code, lang)
        result["spoken_codes"] = {sop_code: spoken}
        result["speech_notes"] = [f"Error code {sop_code}: if you mention it, say it once as '{spoken}'.",
                                  "Never read record IDs (LOG-...) aloud; describe the record instead."]
        result["directive"] = directive + f" If you mention the error code, say it as '{spoken}'."
    result["elapsed_ms"] = round((time.perf_counter() - t0) * 1000, 2)
    log.info("triage channel=%s asset=%s debunked=%d took=%sms", ch, asset_id, len(debunked), result["elapsed_ms"])
    return result


def _draft_brief(current: dict, args: dict[str, Any], ticket_id: str) -> tuple[dict, str | None]:
    asset_id = current.get("asset_id")
    asset = epistemic.COMPANY_CONTEXT.get(asset_id, {}) if asset_id else {}
    fact_texts = [f["text"] for f in current["verified_facts"]]
    sop_code, sop = epistemic.pick_sop(asset_id, current.get("sop_code"),
                                       fact_texts + [u["text"] for u in current["missing_unknowns"]])
    stopped = any(w in " ".join(fact_texts).lower() for w in ("stop", "halt", "down", "not working", "dead", "no power"))
    priority = args.get("priority") if args.get("priority") in ("P1", "P2", "P3") else ("P1" if stopped else "P2")
    brief = {
        "ticket_id": ticket_id,
        "priority": priority,
        "asset": f"{asset_id} — {asset.get('asset_name', 'Unknown asset')}" if asset_id else "Unidentified asset",
        "summary": args.get("summary") or (f"Suspected {sop['fault']}" if sop else "Field issue reported by worker"),
        "verified_facts": fact_texts,
        "debunked_claims": [f"{d['text']} (disproved by {d['evidence']})" for d in current["debunked_claims"]],
        "unverified_guesses": [g["text"] for g in current["unverified_guesses"]],
        "open_unknowns": [u["text"] for u in current["missing_unknowns"] if not u.get("resolved")],
        "recommended_action": (f"Inspect for {sop['fault']} (SOP {sop_code}); replace if confirmed."
                               if sop else "Dispatch technician for on-site diagnosis."),
        "spare_part_reserved": sop["spare_part"] if sop else None,
        "assigned_team": sop["team"] if sop else "Shift Maintenance Supervisor",
        "created_at": time.time(),
    }
    return brief, sop_code


def _spoken_line(kind: str, state: dict, brief: dict) -> str:
    """Confirmation question / routed confirmation in the worker's language, codes spelled for TTS."""
    language = state.get("language") or settings.DEFAULT_LANGUAGE
    part, team = agora_convo.spoken_part_team(state.get("sop_code"), language)
    ticket = phonetics.speak_ticket(brief["ticket_id"], language)
    line = agora_convo.get_profile(language)["speech"][kind].format(ticket=ticket, part=part, team=team)
    return speech_normalizer.normalize_for_speech(line, language)


async def run_propose(ch: str, args: dict[str, Any]) -> dict[str, Any]:
    """CONFIRM stage: draft the critical action (ticket + spare-part reservation) and hold it for approval."""
    current = await store.get(ch)
    if current["status"] == "ROUTED" and current.get("english_brief"):
        brief = current["english_brief"]
        return {"status": "already_routed", "ticket_id": brief["ticket_id"],
                "directive": f"Say: '{_spoken_line('routed', current, brief)}'"}
    existing = current.get("proposed_ticket")
    ticket_id = existing["ticket_id"] if existing else f"SYNC-{next(_ticket_seq)}"
    brief, sop_code = _draft_brief(current, args, ticket_id)
    spoken = _spoken_line("confirm", {**current, "sop_code": sop_code or current.get("sop_code")}, brief)
    part = brief["spare_part_reserved"] or "no spare part"

    def _apply(s: dict) -> None:
        s["status"] = "AWAITING_APPROVAL"
        s["proposed_ticket"] = brief
        s["confirmation_question"] = spoken  # shown on the approval card the instant the gate opens
        s["active_check"] = None  # the diagnostic check was answered
        for u in s["missing_unknowns"]:
            u["resolved"] = True
        store.append_logs(s, [L("ACTION", "ROUTE", f"APPROVAL GATE: proposed {ticket_id} [{brief['priority']}] + "
                                                   f"reserve {part} -> awaiting worker confirmation (voice or manual)")])

    await store.update(ch, _apply)
    yes = ", ".join(agora_convo.get_profile(current.get("language"))["speech"]["yes_words"])
    return {"status": "awaiting_approval", "ticket_id": ticket_id, "proposed_ticket": brief,
            "ticket_id_spoken": phonetics.speak_ticket(ticket_id, current.get("language")),
            "confirmation_question": spoken, "spoken_line": spoken,
            "directive": f"Ask exactly: '{spoken}' Then wait. If the worker confirms ({yes}), call "
                         f"finalize_english_brief. Do not say the ticket as {ticket_id}."}


async def run_route(ch: str, args: dict[str, Any], via: str = "voice") -> dict[str, Any]:
    """AFTER stage: execute the approved action. Server-side gate: without a pending proposal this only proposes."""
    current = await store.get(ch)
    if current["status"] == "ROUTED" and current.get("english_brief"):  # idempotent (voice + button race)
        brief = current["english_brief"]
        spoken = _spoken_line("routed", current, brief)
        return {"status": "routed", "ticket_id": brief["ticket_id"], "english_brief": brief, "spoken_line": spoken,
                "directive": f"The ticket is already routed. Say: '{spoken}'"}
    if current["status"] != "AWAITING_APPROVAL" or not current.get("proposed_ticket"):
        result = await run_propose(ch, args)
        result["status"] = "approval_required"
        await store.log(ch, "WARN", "ROUTE", "finalize called before worker approval -> held at approval gate")
        return result

    brief = dict(current["proposed_ticket"])
    language = current.get("language") or settings.DEFAULT_LANGUAGE
    locale = agora_convo.get_profile(language)["tts_params"]["locale"]
    follow_up = f"Automated Murf {locale} voice check-in scheduled in {settings.FOLLOW_UP_MINUTES} mins"
    now = time.time()
    brief.update(routed_at=now, approved_via=via, follow_up=follow_up,
                 follow_up_due_at=now + settings.FOLLOW_UP_MINUTES * 60,
                 ops_webhook="dispatched" if settings.OPS_WEBHOOK_URL else "logged")
    ticket_id = brief["ticket_id"]

    def _route(s: dict) -> None:
        s["status"] = "ROUTED"
        s["english_brief"] = brief
        s["proposed_ticket"] = None
        s["confirmation_question"] = None
        s["approval"] = {"via": via, "at": now}
        s["follow_up_schedule"] = follow_up
        s["active_check"] = None
        for u in s["missing_unknowns"]:
            u["resolved"] = True
        store.append_logs(s, [
            L("ACTION", "ROUTE", f"APPROVED ({'worker voice' if via == 'voice' else 'supervisor button'}) -> "
                                 f"Created Ticket {ticket_id} [{brief['priority']}] -> Assigned to {brief['assigned_team']}"),
            L("INFO", "TTS", f"FOLLOW-UP: {follow_up}"),
            L("INFO", "ROUTE", "Ops webhook dispatched" if settings.OPS_WEBHOOK_URL
              else "Ops webhook: OPS_WEBHOOK_URL not set, brief logged locally"),
        ])

    snap = await store.update(ch, _route)
    snap = await set_engineer_ringing(ch)  # AFTER: the lead engineer's phone rings
    if settings.OPS_WEBHOOK_URL:
        asyncio.get_running_loop().create_task(_dispatch_ops(brief))
    log.info("routed channel=%s ticket=%s priority=%s via=%s", ch, ticket_id, brief["priority"], via)
    spoken = _spoken_line("routed", snap, brief)
    result = {"status": "routed", "ticket_id": ticket_id, "english_brief": brief, "spoken_line": spoken,
              "follow_up_schedule": follow_up, "directive": f"Say: '{spoken}'"}
    lang = _phonetic_lang(snap)
    if lang:
        result["ticket_id_spoken"] = phonetics.speak_ticket(ticket_id, lang)
        result["speech_notes"] = [f"Ticket {ticket_id}: say only its number, '{result['ticket_id_spoken']}'.",
                                  "Never read the spare part code aloud; call it by its name."]
        result["directive"] += f" Never say the ticket as {ticket_id}."
    return result


async def _dispatch_ops(brief: dict) -> None:
    try:
        await _client().post(settings.OPS_WEBHOOK_URL, json={"type": "syncup.work_order", "brief": brief}, timeout=5)
    except httpx.HTTPError as e:
        log.warning("ops webhook failed: %s", e)


def _phonetic_lang(state: dict) -> str | None:
    """The channel language if its TTS needs codes spelled in native script (ml/kn/ta), else None."""
    lang = state.get("language")
    if lang and agora_convo.get_profile(lang).get("speak_codes_phonetically") and phonetics.has_table(lang):
        return lang
    return None


def _speaks_codes_phonetically(state: dict) -> bool:
    return _phonetic_lang(state) is not None


def asset_context(asset_id: str | None, source: str) -> dict | None:
    asset = epistemic.COMPANY_CONTEXT.get(asset_id or "")
    if not asset:
        return None
    return {
        "asset_id": asset_id,
        "asset_name": asset["asset_name"],
        "source": source,
        "loaded_at": time.time(),
        "maintenance_logs": [{k: lg[k] for k in ("log_id", "date", "component", "status")}
                             for lg in asset.get("maintenance_logs", [])],
        "sops": [{"code": c, "fault": r["fault"], "spare_part": r["spare_part"], "team": r["team"]}
                 for c, r in asset.get("sop_rules", {}).items()],
    }


def _context_log(ctx: dict) -> dict:
    hist = "; ".join(f"{lg['log_id']} {lg['component']} {lg['status']} ({lg['date']})" for lg in ctx["maintenance_logs"])
    return L("INFO", "DB", f"BEFORE: context loaded via {ctx['source'].upper()} -> {ctx['asset_id']} "
                           f"{ctx['asset_name']} | history: {hist}")


async def _graceful(ch: str, where: str, coro) -> dict[str, Any]:
    """ERROR_HANDLED stage: a tool failure never kills the call; the agent apologises and asks again."""
    try:
        return await coro
    except HTTPException:
        raise
    except Exception as e:  # noqa: BLE001
        log.exception("%s failed on %s", where, ch)
        state = await store.get(ch)

        def _err(s: dict) -> None:
            s["status"] = "ERROR_HANDLED"
            s["error"] = f"{where}: {type(e).__name__}"
            store.append_logs(s, [L("WARN", "ROUTE", f"ERROR HANDLED in {where}: {type(e).__name__} -> agent "
                                                     f"asks the worker to repeat; state preserved")])

        await store.update(ch, _err)
        return {"status": "error_handled",
                "directive": f"Say: '{agora_convo.get_profile(state.get('language'))['failure']}'"}


# ----------------------------------------------------------------------------- health & preflight
@app.get("/health")
async def health():
    return {
        "status": "ok",
        "company_context_assets": sorted(epistemic.COMPANY_CONTEXT.keys()),
        "live_agent_ready": not settings.missing_for_live_agent(),
        "missing_env": settings.missing_for_live_agent(),
        "warnings": settings.live_warnings(),
        "llm": {"credential_mode": settings.LLM_CREDENTIAL_MODE, "model": settings.LLM_MODEL},
        "languages": list(agora_convo.LANGUAGE_PROFILES),
    }


@app.get("/api/languages")
async def languages():
    return [
        {"code": code, "label": p["label"], "short": p["short"], "asr_language": p["asr_language"],
         "murf_voice_id": p["tts_params"]["voiceId"], "greeting": p["greeting"],
         "tuning": {env: agora_convo.compute_tuning(code, env) for env in agora_convo.ACOUSTIC_PROFILES}}
        for code, p in agora_convo.LANGUAGE_PROFILES.items()
    ]


@app.get("/api/acoustics")
async def acoustics():
    return [{"id": k, **v} for k, v in agora_convo.ACOUSTIC_PROFILES.items()]


@app.get("/api/assets/{asset_id}")
async def asset_info(asset_id: str):
    ctx = asset_context(asset_id, "lookup")
    if not ctx:
        raise HTTPException(404, f"Unknown asset {asset_id}")
    return ctx


_murf_cache: dict[str, Any] = {"ts": 0.0, "val": None}
_http: httpx.AsyncClient | None = None


def _client() -> httpx.AsyncClient:
    """Shared pooled client: keeps TLS connections warm so repeat preflights cost one RTT, not a handshake."""
    global _http
    if _http is None or _http.is_closed:
        _http = httpx.AsyncClient(http2=False, limits=httpx.Limits(max_keepalive_connections=8),
                                  timeout=httpx.Timeout(2.5, connect=1.0))
    return _http
PLACEHOLDER_TUNNELS = ("your-tunnel-url", "example.com", "localhost", "127.0.0.1")


async def _check_murf(client: httpx.AsyncClient) -> str:
    if not settings.MURF_API_KEY:
        return "MISSING_KEY"
    if _murf_cache["val"] == "OK" and time.time() - _murf_cache["ts"] < 60:
        return "OK"
    try:
        r = await client.get(settings.MURF_VOICES_URL, params={"model": "falcon-2.1"},
                             headers={"api-key": settings.MURF_API_KEY}, timeout=2.5)
        val = "OK" if r.status_code == 200 else "AUTH_ERROR" if r.status_code in (401, 403) else f"HTTP_{r.status_code}"
    except httpx.HTTPError:
        val = "UNREACHABLE"
    _murf_cache.update(ts=time.time(), val=val)
    return val


_agora_cache: dict[str, Any] = {"ts": 0.0, "val": None}


async def _check_agora_rest(client: httpx.AsyncClient) -> str:
    if not (settings.AGORA_CUSTOMER_ID and settings.AGORA_CUSTOMER_SECRET):
        return "MISSING_KEY"
    if _agora_cache["val"] == "OK" and time.time() - _agora_cache["ts"] < 60:
        return "OK"
    try:
        r = await client.get("https://api.agora.io/dev/v1/projects", timeout=2.5,
                             auth=(settings.AGORA_CUSTOMER_ID, settings.AGORA_CUSTOMER_SECRET))
        if r.status_code in (401, 403):
            val = "AUTH_ERROR"
        else:
            ids = {p.get("vendor_key") for p in r.json().get("projects", [])}
            val = "OK" if settings.AGORA_APP_ID in ids else "APP_ID_NOT_IN_ACCOUNT"
    except (httpx.HTTPError, ValueError):
        val = "UNREACHABLE"
    _agora_cache.update(ts=time.time(), val=val)
    return val


def _tunnel_shape() -> str:
    url = settings.PUBLIC_WEBHOOK_BASE_URL
    if not url.startswith("https://") or any(p in url for p in PLACEHOLDER_TUNNELS):
        return "INVALID_TUNNEL"
    return "OK"


async def _check_tunnel(client: httpx.AsyncClient) -> str:
    if _tunnel_shape() != "OK":
        return "INVALID_TUNNEL"
    try:  # round-trip through the public tunnel back into this very server
        r = await client.get(f"{settings.PUBLIC_WEBHOOK_BASE_URL}/health", timeout=1.2,
                             headers={"ngrok-skip-browser-warning": "1"})
        return "OK" if r.status_code == 200 and r.json().get("status") == "ok" else "UNREACHABLE"
    except (httpx.HTTPError, ValueError):
        return "UNREACHABLE"


async def _bounded(coro, budget: float, fallback: str) -> str:
    try:
        return await asyncio.wait_for(coro, budget)
    except asyncio.TimeoutError:
        return fallback


@app.get("/api/preflight")
async def preflight():
    """All checks run concurrently and are individually time-boxed so the endpoint answers in < 1.5 s."""
    t0 = time.perf_counter()
    client = _client()
    murf, agora_rest, tunnel = await asyncio.gather(
        _bounded(_check_murf(client), 1.3, "SLOW"),
        _bounded(_check_agora_rest(client), 1.3, "SLOW"),
        _bounded(_check_tunnel(client), 1.0, "UNREACHABLE"),
    )
    creds = all([settings.AGORA_APP_ID, settings.AGORA_APP_CERTIFICATE,
                 settings.AGORA_CUSTOMER_ID, settings.AGORA_CUSTOMER_SECRET])
    hints = []
    if not settings.AGORA_APP_CERTIFICATE:
        hints.append("Add AGORA_APP_CERTIFICATE (Agora Console > Project > Config) to backend/.env")
    if agora_rest not in ("OK",):
        hints.append(f"Agora REST check: {agora_rest}")
    if murf != "OK":
        hints.append(f"Murf check: {murf}")
    if tunnel != "OK":
        hints.append("Run `ngrok http 8000` and set PUBLIC_WEBHOOK_BASE_URL to its https URL, then restart uvicorn")
    return {
        "agora_creds": creds,
        "agora_rest": agora_rest,
        "murf_api": murf,
        "webhook_tunnel": tunnel if tunnel != "UNREACHABLE" or _tunnel_shape() == "OK" else "INVALID_TUNNEL",
        "llm": {"credential_mode": settings.LLM_CREDENTIAL_MODE, "model": settings.LLM_MODEL},
        "ready": creds and agora_rest == "OK" and murf == "OK" and tunnel == "OK",
        "hints": hints,
        "elapsed_ms": round((time.perf_counter() - t0) * 1000),
    }


# ----------------------------------------------------------------------------- agent hygiene
def new_channel_name() -> str:
    return f"syncup-{int(time.time() * 1000)}"


async def reap_agents(kind: str | None = None, reason: str = "") -> list[str]:
    """Stop every agent we still consider alive (optionally only one kind) so two agents can never overlap."""
    stopped = []
    for agent_id, meta in store.agents(kind):
        try:
            await agora_convo.stop_convo_agent(agent_id)
        except (agora_convo.AgoraConvoError, httpx.HTTPError) as e:
            log.info("reap %s: %s", agent_id, e)  # already gone on Agora's side: fine
        store.unregister_agent(agent_id)
        stop_history_sync(f"{meta['channel']}:{'engineer' if meta['kind'] == 'engineer' else 'worker'}")
        stopped.append(agent_id)
        log.info("reaped %s agent %s on %s %s", meta["kind"], agent_id, meta["channel"], reason)
    return stopped


@app.post("/api/session/cleanup")
async def session_cleanup():
    """One-click: stop every Agora agent this backend started (worker + engineer), stop all transcript syncs."""
    channels = {m["channel"] for _, m in store.agents()}
    stopped = await reap_agents(reason="(manual cleanup)")
    for key in list(_pollers):
        stop_history_sync(key)
    for ch in channels:
        base = ch.removesuffix("-eng")

        def _clear(s: dict) -> None:
            s["agent_id"] = None
            if s.get("escalation") and s["escalation"]["status"] not in ("completed", "failed"):
                s["escalation"]["status"] = "completed"
            store.append_logs(s, [L("ACTION", "RTC", f"CLEANUP: stopped {len(stopped)} agent(s)")])

        await store.update(base, _clear)
    return {"stopped": stopped, "count": len(stopped)}


# ----------------------------------------------------------------------------- session lifecycle
def _tuning_log(t: dict, profile: dict) -> list[dict]:
    vol = f" vol {t['volume_offset']:+d}" if t["volume_offset"] is not None else ""
    return [
        L("INFO", "ASR", f"ARES {profile['asr_language']} | {agora_convo.get_acoustics(t['environment'])['label']}: "
                         f"VAD {t['vad_threshold']} / silence {t['silence_ms']}ms / barge-in {t['interrupt_ms']}ms "
                         f"(speaking {t['speaking_interrupt_ms']}ms) / prefix {t['prefix_ms']}ms"),
        L("INFO", "TTS", f"PROSODY {t['language']}: LLM {settings.LLM_MODEL} temp {t['temperature']:.2f} "
                         f"presence {t['presence_penalty']:.2f} | Murf {t['model']} {t['voice']} {t['style']} "
                         f"rate {t['rate']:+d} pitch {t['pitch']:+d}{vol} @24kHz"),
    ]


async def _previous_context(ch: str, asset_id: str) -> dict | None:
    prev = (await store.get(ch)).get("asset_context")
    return prev if prev and prev.get("asset_id") == asset_id else None


@app.post("/api/session/start")
async def session_start(req: SessionStartRequest):
    missing = settings.missing_for_live_agent()
    if missing:
        raise HTTPException(503, f"Missing env vars in backend/.env: {', '.join(missing)}")
    if req.language not in agora_convo.LANGUAGE_PROFILES:
        raise HTTPException(400, f"Unsupported language {req.language}")
    if req.environment not in agora_convo.ACOUSTIC_PROFILES:
        raise HTTPException(400, f"Unsupported environment {req.environment}")
    if not req.channel_name or req.channel_name == "auto":
        req.channel_name = new_channel_name()
    profile = agora_convo.get_profile(req.language)
    tuning = agora_convo.compute_tuning(req.language, req.environment)
    reaped = await reap_agents(reason=f"(before new session {req.channel_name})")  # no zombie can talk over us
    tokens = agora_tokens.build_session_tokens(req.channel_name)
    try:
        agent = await agora_convo.start_convo_agent(req.channel_name, tokens["agent_rtc_token"],
                                                    req.language, req.asset_hint, req.environment)
    except agora_convo.AgoraConvoError as e:
        log.error("Agora /join failed: %s", e)

        def _err(s: dict) -> None:
            s["status"] = "ERROR_HANDLED"
            s["error"] = f"Agora /join failed ({e.status_code})"
            store.append_logs(s, [L("WARN", "RTC", f"Agora /join failed ({e.status_code}): {e.detail[:160]}"
                                                   " -> use Demo Sim or retry")])

        await store.update(req.channel_name, _err)
        raise HTTPException(502, f"Agora /join failed ({e.status_code}): {e.detail}")
    agent_id = agent.get("agent_id")
    store.register_agent(agent_id, req.channel_name, "worker")
    ctx = (await _previous_context(req.channel_name, req.asset_hint)
           or (await _previous_context(req.previous_channel, req.asset_hint) if req.previous_channel else None)
           or asset_context(req.asset_hint, "scenario"))
    await store.reset(req.channel_name, status="BEFORE_CONTEXT", demo_stage="WORKER_CALL", agent_id=agent_id, language=req.language,
                      asset_hint=req.asset_hint, environment=req.environment, asset_context=ctx)
    await store.update(req.channel_name, lambda s: store.append_logs(s, [
        L("ACTION", "RTC", f"Agent joined fresh channel {req.channel_name} in {profile['short']} ({req.language}) "
                           f"| agent_id={agent_id}"),
        *([L("INFO", "RTC", f"Zombie guard: stopped {len(reaped)} previous agent(s) before joining")] if reaped else []),
        *([_context_log(ctx)] if ctx else []),
        *_tuning_log(tuning, profile),
        L("INFO", "RTC", f"RTM transcripts on (+ REST history sync) | HITL approval gate on | scenario {req.asset_hint}"),
    ]))
    start_history_sync(req.channel_name, agent_id, "worker")
    return {
        "app_id": settings.AGORA_APP_ID,
        "channel_name": req.channel_name,
        "uid": settings.USER_UID,
        "agent_uid": settings.AGENT_UID,
        "rtc_token": tokens["user_rtc_token"],
        "rtm_token": tokens["user_rtm_token"],
        "agent_id": agent_id,
        "language": req.language,
        "asset_hint": req.asset_hint,
        "environment": req.environment,
        "client_mic_gain": tuning["client_mic_gain"],
        "tuning": {k: tuning[k] for k in ("temperature", "presence_penalty", "voice", "style", "rate", "pitch",
                                          "volume_offset", "vad_threshold", "interrupt_ms", "silence_ms")},
    }


@app.post("/api/session/stop")
async def session_stop(req: SessionStopRequest):
    agent_id = req.agent_id or (await store.get(req.channel_name)).get("agent_id")
    stop_history_sync(f"{req.channel_name}:worker")
    await end_escalation(req.channel_name)
    result: dict = {"agent_id": agent_id}
    store.unregister_agent(agent_id)
    if agent_id:
        try:
            result = await agora_convo.stop_convo_agent(agent_id)
        except agora_convo.AgoraConvoError as e:
            log.warning("Agora /leave failed (agent may already be gone): %s", e)
            result = {"agent_id": agent_id, "warning": e.detail}

    def _ended(s: dict) -> None:  # keep the stage: a pending approval can still be approved from the UI
        if s.get("english_brief"):
            s["status"] = "ROUTED"
        s["agent_id"] = None
        store.append_logs(s, [L("INFO", "RTC", f"Session ended | agent {agent_id or '-'} left channel")])

    state = await store.update(req.channel_name, _ended)
    return {"status": state["status"], "agora": result, "state": state}


class ContextRequest(BaseModel):
    asset_id: str = "LINE-03"
    source: str = "qr"


@app.post("/api/session/{channel_name}/context")
async def load_context(channel_name: str, req: ContextRequest):
    """BEFORE stage: a QR scan on the machine pre-loads its maintenance history before the voice call starts."""
    ctx = asset_context(req.asset_id, req.source)
    if not ctx:
        raise HTTPException(404, f"Unknown asset {req.asset_id}")
    current = await store.get(channel_name)
    if current.get("agent_id"):  # live call: attach context without wiping the conversation
        await store.update(channel_name, lambda s: (s.update(asset_context=ctx, demo_stage="WORKER_CALL"),
                                                    store.append_logs(s, [_context_log(ctx)])))
    else:
        await store.reset(channel_name, status="BEFORE_CONTEXT", demo_stage="WORKER_CALL", asset_context=ctx,
                          asset_hint=req.asset_id)
        await store.log(channel_name, "ACTION", "DB", f"QR scanned on {req.asset_id} ({ctx['asset_name']})")
        await store.update(channel_name, lambda s: store.append_logs(s, [_context_log(ctx)]))
    return ctx


@app.post("/api/session/{channel_name}/approve")
async def approve(channel_name: str):
    """CONFIRM -> AFTER via the supervisor's 'Approve & Route Now' button (same code path as a voice 'yes')."""
    state = await store.get(channel_name)
    if state["status"] != "AWAITING_APPROVAL" or not state.get("proposed_ticket"):
        raise HTTPException(409, f"Nothing awaiting approval (status {state['status']})")
    result = await run_route(channel_name, {}, via="manual")
    agent_id = state.get("agent_id")
    if agent_id and not state.get("simulated"):  # tell the worker out loud, in their language, through Murf
        try:
            await agora_convo.speak_agent(agent_id, result["spoken_line"])
            await store.log(channel_name, "INFO", "TTS", f"Agent /speak: {result['spoken_line']}")
        except (agora_convo.AgoraConvoError, httpx.HTTPError) as e:
            await store.log(channel_name, "WARN", "TTS", f"Agent /speak failed: {str(e)[:120]}")
    return result


@app.get("/api/session/{channel_name}/state")
async def session_state(channel_name: str):
    return await store.get(channel_name)


@app.get("/api/session/{channel_name}/stream")
async def session_stream(channel_name: str, request: Request):
    queue = store.subscribe(channel_name)

    async def events():
        try:
            yield f"event: state\ndata: {json.dumps(await store.get(channel_name))}\n\n"
            while True:
                if await request.is_disconnected():
                    break
                try:
                    snapshot = await asyncio.wait_for(queue.get(), timeout=15)
                    yield f"event: state\ndata: {json.dumps(snapshot)}\n\n"
                except asyncio.TimeoutError:
                    yield ": keep-alive\n\n"
        finally:
            store.unsubscribe(channel_name, queue)

    return StreamingResponse(events(), media_type="text/event-stream",
                             headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"})


# ----------------------------------------------------------------------------- live transcript sync (REST fallback)
# Captions normally arrive in the browser over Agora RTM. If RTM is unavailable (Signaling disabled, blocked
# network), the chat would freeze, so the backend also polls Agora's GET /agents/{id}/history and streams new
# turns over SSE. The browser shows RTM captions when it has them and these otherwise.
_pollers: dict[str, asyncio.Task] = {}
HISTORY_POLL_S = 0.8


def _transcript(role: str, text: str, source: str, uid: str) -> dict:
    return {"id": uid, "role": role, "text": text, "isFinal": True,
            "ts": store.make_log("INFO", "ASR", "")["ts"], "source": source}


def start_history_sync(ch: str, agent_id: str, target: str) -> None:
    """target 'worker' -> state.transcripts; 'engineer' -> state.escalation.transcripts."""
    key = f"{ch}:{target}"
    stop_history_sync(key)

    async def loop() -> None:
        seen, misses = 0, 0
        while True:
            await asyncio.sleep(HISTORY_POLL_S)
            try:
                items = await agora_convo.get_history(agent_id, _client())
            except httpx.HTTPError:
                items = None
            if items is None:
                misses += 1
                if misses > 10:  # agent gone for ~8 s
                    return
                continue
            misses = 0
            if len(items) <= seen:
                continue
            new, start = items[seen:], seen
            seen = len(items)
            if target == "worker":
                entries = [_transcript("worker" if c["role"] == "user" else "agent", c["content"], "history",
                                       f"h-{agent_id[-6:]}-{start + i}") for i, c in enumerate(new)]
                logs = [L("INFO", "ASR" if e["role"] == "worker" else "TTS",
                          f"{'Worker' if e['role'] == 'worker' else 'SyncUp'}: {e['text']}") for e in entries]
                for lg in logs:
                    lg["id"] = "hist-" + lg["id"]  # browser hides these when RTM captions are flowing

                def _apply(s: dict) -> None:
                    s.setdefault("transcripts", []).extend(entries)
                    store.append_logs(s, logs)
            else:
                entries = [_transcript("engineer" if c["role"] == "user" else "agent", c["content"], "history",
                                       f"e-{agent_id[-6:]}-{start + i}") for i, c in enumerate(new)]

                def _apply(s: dict) -> None:
                    esc = s.get("escalation")
                    if not esc or esc.get("agent_id") != agent_id:
                        return
                    esc.setdefault("transcripts", []).extend(entries)
                    if esc["status"] in ("dialing", "ringing"):
                        esc["status"] = "connected"
                        esc["connected_at"] = time.time()
                    store.append_logs(s, [L("INFO", "TTS" if e["role"] == "agent" else "ASR",
                                            f"{'SyncUp → engineer' if e['role'] == 'agent' else 'Engineer'}: {e['text']}")
                                          for e in entries])
            await store.update(ch, _apply)

    _pollers[key] = asyncio.get_running_loop().create_task(loop())


def stop_history_sync(key: str) -> None:
    task = _pollers.pop(key, None)
    if task and not task.done():
        task.cancel()


# ----------------------------------------------------------------------------- AFTER: outbound call to the lead engineer
# Demo flow (state.demo_stage): QR_READY -> WORKER_CALL -> ENGINEER_RINGING -> ENGINEER_CONNECTED -> DISPATCH_CONFIRMED.
# The epistemic `status` (BEFORE_CONTEXT .. ROUTED) still runs underneath, including the human-approval gate.
ASSET_SPOKEN = {"LINE-03": "Packaging Line 3", "GATE-02": "the Gate 2 dispatch scanner"}
PRIORITY_SPOKEN = {"P1": "priority one", "P2": "priority two", "P3": "priority three"}
COMPONENT_SHORT = {"Main Gearbox": ("Gearbox", "ഗിയർബോക്സ്"), "Main Server Cluster SRV-BLR-01": ("The server", "സെർവർ")}
FAULT_SHORT = {"E-04": ("Panel B thermal relay tripped", "പാനൽ ബി തെർമൽ റിലേ ട്രിപ്പ് ആയി"),
               "NO_POWER": ("the Gate two PoE adapter has no power", "ഗേറ്റ് ടു പി ഒ ഇ അഡാപ്റ്റർ ഓഫ് ആണ്")}
NAME_ML = {"Arjun": "അർജുൻ", "Priya": "പ്രിയ", "Anil": "അനിൽ"}
ENGINEER_LANGUAGES = ("en-IN", "ml-IN")


def engineer_greeting(state: dict, eng: dict, language: str = "en-IN") -> str:
    """Short (~25 words), fully spoken-form opener the agent says the instant the engineer answers."""
    brief = state["english_brief"]
    asset_id, sop_code = state.get("asset_id") or "", state.get("sop_code")
    ml = language == "ml-IN"
    code = speech_normalizer.speak_code(sop_code, language) if sop_code and any(c.isdigit() for c in sop_code) else ""
    asset = speech_normalizer.normalize_for_speech(asset_id, language) if asset_id else ("യന്ത്രം" if ml else "The machine")
    debunked = [d for d in state.get("debunked_claims", []) if d.get("component")]
    short = COMPONENT_SHORT.get(debunked[0]["component"], (debunked[0]["component"], debunked[0]["component"])) if debunked else None
    fault = FAULT_SHORT.get(sop_code or "", ("the fault is confirmed", "തകരാർ ഉറപ്പായി"))
    codes = phonetics.find_codes(brief.get("spare_part_reserved") or "")
    part = speech_normalizer.speak_code(codes[0], language) if codes else ""
    if ml:
        return (f"ഹായ് {NAME_ML.get(eng['first'], eng['first'])}, സിങ്ക് അപ്പ് ഡിസ്പാച്ച് ആണ്. {asset} "
                + (f"{code} എററിൽ നിന്നു. " if code else "നിന്നു. ")
                + (f"{short[1]} ഓക്കെയാണ്; " if short else "") + f"{fault[1]}. "
                + (f"{part} പാർട്ട് റിസർവ് ചെയ്തു. " if part else "") + "ഡിസ്പാച്ച് ഉറപ്പിക്കട്ടെ?")
    return (f"Hi {eng['first']}, SyncUp Dispatch here. {asset} stopped" + (f" with {code}. " if code else ". ")
            + (f"{short[0]} is fine; " if short else "") + f"{fault[0][0].upper() + fault[0][1:] if not short else fault[0]}. "
            + (f"Part {part} is reserved. " if part else "") + "Confirming dispatch?")


def escalation_briefing(state: dict, eng: dict, language: str = "en-IN") -> dict:
    """Facts for the engineer agent's prompt + its opener. Everything spoken is already in spoken form."""
    brief = state["english_brief"]
    asset_id = state.get("asset_id") or ""
    sop_code = state.get("sop_code")
    part_name, _ = agora_convo.spoken_part_team(sop_code, "en-IN")
    part_raw = brief.get("spare_part_reserved") or ""
    codes = phonetics.find_codes(part_raw)
    location = part_raw[part_raw.find("(") + 1:part_raw.find(")")] if "(" in part_raw else ""
    location = location[:1].lower() + location[1:]
    ruled = [f"the {d['component'].lower()} — it is {phonetics.natural_status(d['status'])}, {d['date']}"
             for d in state.get("debunked_claims", []) if d.get("component")]
    profile = agora_convo.get_profile(language)
    return {
        "opener": engineer_greeting(state, eng, language),
        "language_rule": None if language == "en-IN" else profile["prompt_lang_instruction"],
        "asset": f"{ASSET_SPOKEN.get(asset_id, 'the machine')} ({brief['asset']})",
        "problem": brief.get("summary") or "confirmed fault",
        "worker": state.get("worker_name") or "the operator",
        "facts": brief.get("verified_facts", []),
        "ruled_out": ruled,
        "ticket_spoken": phonetics.speak_ticket(brief["ticket_id"], language),
        "priority_spoken": PRIORITY_SPOKEN.get(brief["priority"], "high priority"),
        "part_spoken": f"a spare {part_name}{f', {location}' if location else ''}" if part_raw else "none",
        "part_code_spoken": speech_normalizer.speak_code(codes[0], language) if codes else "not applicable",
        "action": brief.get("recommended_action", ""),
    }


def _escalation_record(state: dict, mode: str, language: str = "en-IN", channel: str | None = None) -> tuple[dict, dict]:
    eng = agora_convo.engineer_for(state["english_brief"].get("assigned_team"))
    briefing = escalation_briefing(state, eng, language)
    return eng, {"status": "connected", "mode": mode, "engineer": eng, "channel": channel or f"{state['channel']}-eng",
                 "agent_id": None, "opener": briefing["opener"], "transcripts": [], "eta_minutes": None,
                 "accepted": None, "notes": "", "started_at": time.time(), "connected_at": time.time(),
                 "ticket_id": state["english_brief"]["ticket_id"], "language": language}


async def set_engineer_ringing(ch: str) -> dict:
    """Triage done -> the lead engineer's phone rings with an incoming call from SyncUp Dispatch."""
    state = await store.get(ch)
    eng = agora_convo.engineer_for(state["english_brief"].get("assigned_team"))
    summary = speech_normalizer.normalize_for_speech(engineer_greeting(state, eng, "en-IN"), "en-IN")

    def _ring(s: dict) -> None:
        s["demo_stage"] = "ENGINEER_RINGING"
        s["engineer_brief"] = {"engineer": eng, "spoken_summary": summary, "ticket_id": s["english_brief"]["ticket_id"],
                               "priority": s["english_brief"]["priority"], "asset_id": s.get("asset_id")}
        store.append_logs(s, [L("ACTION", "RTC", f"OUTBOUND CALL: ringing {eng['name']} ({eng['role']}) from "
                                                 f"SyncUp Dispatch | {s['english_brief']['ticket_id']}")])

    return await store.update(ch, _ring)


async def run_engineer_ack(ch: str, args: dict[str, Any]) -> dict[str, Any]:
    """Engineer confirmed (or declined) dispatch on the outbound call: record it and prepare the worker update."""
    state = await store.get(ch)
    esc = state.get("escalation")
    if not esc:
        raise HTTPException(409, "No engineer call in progress")
    try:
        eta = max(0, int(float(args.get("eta_minutes") or 0)))
    except (TypeError, ValueError):
        eta = 0
    accepted = str(args.get("accepted")).lower() not in ("false", "0", "no", "none")
    notes = str(args.get("notes") or "").strip()
    eng = esc["engineer"]
    language = state.get("language") or settings.DEFAULT_LANGUAGE
    worker_line = (speech_normalizer.normalize_for_speech(agora_convo.get_profile(language)["speech"]["eta"].format(
        eta=phonetics.speak_minutes(eta or 15, language)), language) if accepted else None)

    def _apply(s: dict) -> None:
        e = s.get("escalation") or {}
        e.update(status="acknowledged", eta_minutes=eta or None, accepted=accepted, notes=notes, acked_at=time.time())
        if accepted:
            s["demo_stage"] = "DISPATCH_CONFIRMED"
        if s.get("english_brief"):
            s["english_brief"]["engineer"] = {"name": eng["name"], "eta_minutes": eta or None, "accepted": accepted}
        store.append_logs(s, [L("ACTION", "ROUTE", f"{'DISPATCH CONFIRMED' if accepted else 'ENGINEER DECLINED'}: "
                                                   f"{eng['name']} | {e.get('ticket_id')}"
                                                   f"{f' | ETA {eta} min' if eta else ''}{f' | {notes}' if notes else ''}")])

    await store.update(ch, _apply)
    if worker_line:  # told to the worker after the engineer line closes (never two voices at once)
        await store.update(ch, lambda s: s["escalation"].update(pending_worker_update=worker_line))
    return {"status": "acknowledged", "eta_minutes": eta, "accepted": accepted, "worker_update": worker_line,
            "spoken_line": worker_line or "",
            "directive": f"Thank {eng['first']} warmly in one short sentence, say dispatch is logged, and say goodbye."}


class EngineerRequest(BaseModel):
    channel_name: str
    language: str = "en-IN"  # engineer briefing language: en-IN (default, judges) or ml-IN
    eta_minutes: int | None = None


@app.post("/api/engineer/ring")
async def engineer_ring(req: EngineerRequest):
    """Presenter shortcut: finish triage (supervisor approval) and ring the lead engineer now."""
    state = await store.get(req.channel_name)
    if state["status"] == "ROUTED" and state.get("english_brief"):
        snap = await set_engineer_ringing(req.channel_name)
    else:
        if not state.get("proposed_ticket"):
            await run_propose(req.channel_name, {})
        await run_route(req.channel_name, {}, via="manual")  # rings automatically once routed
        snap = await store.get(req.channel_name)
    return {"demo_stage": snap["demo_stage"], "ticket_id": snap["english_brief"]["ticket_id"]}


@app.post("/api/engineer/answer")
async def engineer_answer(req: EngineerRequest):
    """Judge pressed the green Answer button: stop every other agent, start the engineer agent on a fresh channel;
    the agent speaks first with the verified incident summary."""
    state = await store.get(req.channel_name)
    if not state.get("english_brief"):
        raise HTTPException(409, "No routed incident to brief the engineer on")
    language = req.language if req.language in ENGINEER_LANGUAGES else "en-IN"
    if state.get("simulated"):
        eng, record = _escalation_record(state, "sim", language)
        record["agent_id"] = "sim-engineer"
        await store.update(req.channel_name, lambda s: (s.update(escalation=record, demo_stage="ENGINEER_CONNECTED"),
                                                       store.append_logs(s, [L("ACTION", "RTC", f"Engineer {eng['name']} answered")])))
        return {"simulated": True, "engineer": eng}
    missing = settings.missing_for_live_agent()
    if missing:
        raise HTTPException(503, f"Missing env vars in backend/.env: {', '.join(missing)}")
    reaped = await reap_agents(reason="(engineer answered)")  # the worker agent hands over; never two agents
    stop_history_sync(f"{req.channel_name}:worker")
    eng_ch = f"syncup-eng-{int(time.time() * 1000)}"
    eng, record = _escalation_record(state, "live", language, eng_ch)
    briefing = escalation_briefing(state, eng, language)
    tokens = agora_tokens.build_session_tokens(eng_ch)
    try:
        agent = await agora_convo.start_engineer_agent(eng_ch, tokens["agent_rtc_token"], req.channel_name, eng,
                                                       briefing, state.get("environment"), language)
    except agora_convo.AgoraConvoError as e:
        await store.log(req.channel_name, "WARN", "RTC", f"Engineer call failed ({e.status_code}): {e.detail[:140]}")
        raise HTTPException(502, f"Engineer call failed ({e.status_code}): {e.detail}")
    record["agent_id"] = agent.get("agent_id")
    store.register_agent(record["agent_id"], eng_ch, "engineer")

    def _connected(s: dict) -> None:
        s.update(escalation=record, demo_stage="ENGINEER_CONNECTED", agent_id=None)
        store.append_logs(s, [L("ACTION", "RTC", f"Engineer {eng['name']} answered | worker agent handed over "
                                                 f"({len(reaped)} stopped) | {eng_ch} | Murf {language}")])

    await store.update(req.channel_name, _connected)
    start_history_sync(req.channel_name, record["agent_id"], "engineer")
    return {"app_id": settings.AGORA_APP_ID, "channel_name": eng_ch, "uid": settings.USER_UID,
            "rtc_token": tokens["user_rtc_token"], "agent_id": record["agent_id"], "engineer": eng,
            "greeting": record["opener"], "language": language}


@app.post("/api/engineer/confirm")
async def engineer_confirm(req: EngineerRequest):
    """'Confirm Dispatch' tapped on the engineer's phone (same path as the agent's acknowledge tool)."""
    return await run_engineer_ack(req.channel_name, {"accepted": True, "eta_minutes": req.eta_minutes or 15,
                                                     "notes": "Confirmed on engineer device"})


@app.post("/api/engineer/decline")
async def engineer_decline(req: EngineerRequest):
    await end_escalation(req.channel_name)
    await store.update(req.channel_name, lambda s: (s.update(demo_stage="WORKER_CALL", escalation=None),
                                                   store.append_logs(s, [L("WARN", "RTC", "Engineer declined the call - ring again when ready")])))
    return {"demo_stage": "WORKER_CALL"}


async def end_escalation(channel_name: str) -> dict:
    state = await store.get(channel_name)
    esc = state.get("escalation")
    if not esc:
        return {"status": "none"}
    stop_history_sync(f"{channel_name}:engineer")
    store.unregister_agent(esc.get("agent_id"))
    if esc.get("agent_id") and esc.get("mode") == "live" and esc["status"] not in ("completed", "failed"):
        try:
            await agora_convo.stop_convo_agent(esc["agent_id"])
        except agora_convo.AgoraConvoError as e:
            log.warning("engineer agent leave failed: %s", e)

    def _done(s: dict) -> None:
        e = s.get("escalation")
        if e and e["status"] not in ("completed", "failed"):
            e["status"] = "completed"
            e["ended_at"] = time.time()
            store.append_logs(s, [L("INFO", "RTC", f"Call with {e['engineer']['name']} ended")])

    snap = await store.update(channel_name, _done)
    pending = (snap.get("escalation") or {}).get("pending_worker_update")
    if pending and snap.get("agent_id") and not snap.get("simulated"):
        try:  # worker call still live: they hear the ETA now that the engineer line is closed
            await agora_convo.speak_agent(snap["agent_id"], pending)
            await store.update(channel_name, lambda s: (s["escalation"].update(pending_worker_update=None),
                                                        store.append_logs(s, [L("INFO", "TTS", f"Told worker: {pending}")])))
        except (agora_convo.AgoraConvoError, httpx.HTTPError) as e:
            await store.log(channel_name, "WARN", "TTS", f"Could not update worker: {str(e)[:120]}")
    elif pending and not snap.get("simulated"):  # worker agent already handed over: deliver as an app message
        entry = _transcript("agent", pending, "history", f"eta-{time.time_ns()}")
        await store.update(channel_name, lambda s: (s["escalation"].update(pending_worker_update=None),
                                                    s.setdefault("transcripts", []).append(entry),
                                                    store.append_logs(s, [L("INFO", "TTS", f"Worker app update: {pending}")])))
    return {"status": snap["escalation"]["status"]}


@app.post("/api/session/{channel_name}/escalation/end")
async def escalation_end(channel_name: str):
    return await end_escalation(channel_name)


# ----------------------------------------------------------------------------- stage fallback: Demo Sim
# Steps: (kind, text-or-tool, arg). "{spoken}" = the spoken_line returned by the preceding tool call.
SIM_SCRIPT_ML = [
    ("context", "LINE-03", None),  # QR_READY -> WORKER_CALL: QR scan pre-loads LOG-891 history
    ("agent", agora_convo.LANGUAGE_PROFILES["ml-IN"]["greeting"], None),
    ("worker", "Line 3 നിന്നുപോയി. Panel-ൽ E-04 error കാണിക്കുന്നു. Gearbox കത്തിപ്പോയി എന്ന് തോന്നുന്നു.", None),
    ("tool", "triage", {"asset_id": "LINE-03",  # guess debunked by LOG-891
                        "verified_facts": ["Packaging Line 3 halted", "Error code E-04 on panel"],
                        "worker_guesses": ["Main gearbox burned out"],
                        "missing_unknowns": ["Thermal relay LED status on Panel B"], "fault_code": "E-04"}),
    ("agent", "ശരി, അങ്ങനെ തോന്നുന്നത് സ്വാഭാവികം. പക്ഷേ, ഗിയർബോക്സ് ആറു ദിവസം മുമ്പ് മാറ്റിയതാണ്. "
              "പാനൽ ബി-യിലെ ലൈറ്റ് ചുവപ്പാണോ?", None),
    ("worker", "അതെ, Panel B-യിൽ LED ചുവപ്പാണ്.", None),
    ("tool", "triage", {"asset_id": "LINE-03", "verified_facts": ["Thermal relay LED on Panel B is glowing red"],
                        "worker_guesses": [], "missing_unknowns": [], "fault_code": "E-04"}),
    ("tool", "propose", {"summary": "Line 3 stopped on E-04: thermal relay on Panel B tripped", "priority": "P1"}),
    ("agent", "{spoken}", "skip_if_routed"),  # human-in-the-loop confirmation question
    ("hold", "", None),
    ("worker", "അതെ, ചെയ്യൂ.", "skip_if_routed"),
    ("tool", "route", {"summary": "Line 3 stopped on E-04: thermal relay on Panel B tripped", "priority": "P1"}),
    ("agent", "{spoken}", None),  # "ticket raised, calling the engineer now" -> ENGINEER_RINGING
    ("ring", "", None),  # judge presses green Answer (auto-answers after a few seconds)
    ("eng_agent", "{opener}", None),
    ("engineer", "Yes, confirmed. Dispatching now. I'll be at Line three in ten minutes.", None),
    ("tool", "ack", {"eta_minutes": 10, "accepted": True, "notes": "Bringing the spare relay"}),  # DISPATCH_CONFIRMED
    ("eng_agent", "Thanks Arjun. Dispatch is logged. Goodbye!", None),
    ("hangup", "", None),
    ("agent", "{worker_update}", None),  # worker hears the ETA in Malayalam
]
_sim_tasks: dict[str, asyncio.Task] = {}


async def _push_transcript(ch: str, role: str, text: str) -> None:
    entry = _transcript(role, text, "sim", f"sim-{time.time_ns()}")
    log_entry = L("INFO", "ASR", f"Worker: {text}") if role == "worker" else L("INFO", "TTS", f"SyncUp: {text}")

    def _apply(s: dict) -> None:
        s.setdefault("transcripts", []).append(entry)
        store.append_logs(s, [log_entry])

    await store.update(ch, _apply)


async def _push_eng_transcript(ch: str, role: str, text: str) -> None:
    entry = _transcript(role, text, "sim", f"sim-e-{time.time_ns()}")

    def _apply(s: dict) -> None:
        esc = s.get("escalation")
        if esc:
            esc["transcripts"].append(entry)
        store.append_logs(s, [L("INFO", "TTS" if role == "agent" else "ASR",
                                f"{'SyncUp → engineer' if role == 'agent' else 'Engineer'}: {text}")])

    await store.update(ch, _apply)


async def _sim_set_call(ch: str, status: str) -> None:
    def _apply(s: dict) -> None:
        e = s.get("escalation")
        if e:
            e["status"] = status
            if status == "connected":
                e["connected_at"] = time.time()
            if status == "completed":
                e["ended_at"] = time.time()
    await store.update(ch, _apply)


async def run_simulation(ch: str, pace: float) -> None:
    tools = {"triage": run_triage, "propose": run_propose, "route": run_route, "ack": run_engineer_ack}
    spoken, worker_update = "", ""
    for kind, a, b in SIM_SCRIPT_ML:
        if kind == "context":
            ctx = asset_context(a, "qr")
            await store.reset(ch, status="BEFORE_CONTEXT", demo_stage="WORKER_CALL", language="ml-IN", asset_hint=a,
                              worker_name="Ramesh", environment="stage_noisy", simulated=True, asset_context=ctx)
            await store.update(ch, lambda s: store.append_logs(s, [
                L("ACTION", "RTC", "DEMO SIM: scripted Malayalam LINE-03 run through the real triage -> approval -> "
                                   "route -> engineer-call engine (no WebRTC needed)"),
                L("ACTION", "DB", f"QR scanned on {a} ({ctx['asset_name']})"), _context_log(ctx)]))
            continue
        await asyncio.sleep(pace * (2.5 if kind == "hold" else 1))
        state = await store.get(ch)
        if kind == "tool":
            result = await tools[a](ch, b)
            spoken = result.get("spoken_line", spoken)
            worker_update = result.get("worker_update") or worker_update
        elif kind == "ring":  # wait for the judge's green Answer, else auto-answer
            for _ in range(int(max(1, pace) * 8)):
                if (await store.get(ch)).get("demo_stage") == "ENGINEER_CONNECTED":
                    break
                await asyncio.sleep(0.5 if pace else 0)
            else:
                await engineer_answer(EngineerRequest(channel_name=ch))
            await asyncio.sleep(pace * 0.5)
        elif kind == "eng_agent":
            await _push_eng_transcript(ch, "agent", a.format(opener=(state.get("escalation") or {}).get("opener", "")))
        elif kind == "engineer":
            await _push_eng_transcript(ch, "engineer", a)
        elif kind == "hangup":
            await _sim_set_call(ch, "completed")
            await store.log(ch, "INFO", "RTC", "Call with engineer ended")
        elif kind in ("agent", "worker"):
            if b == "skip_if_routed" and state["status"] == "ROUTED":
                continue  # a judge already approved
            text = a.format(spoken=spoken, worker_update=worker_update)
            if text:
                await _push_transcript(ch, kind, text)


@app.post("/api/session/{channel_name}/simulate")
async def simulate(channel_name: str, pace: float = Query(1.2, ge=0, le=5), wait: bool = Query(False)):
    """Stage fallback when venue Wi-Fi blocks WebRTC UDP: replays a realistic Malayalam LINE-03 conversation
    through the *real* triage -> propose -> approval -> route -> engineer-call functions, streamed over SSE."""
    running = _sim_tasks.get(channel_name)
    if running and not running.done():
        raise HTTPException(409, "A simulation is already running on this channel")
    if wait:
        await run_simulation(channel_name, pace)
        state = await store.get(channel_name)
        return {"status": "completed", "channel": channel_name, "ticket_id": (state["english_brief"] or {}).get("ticket_id")}
    _sim_tasks[channel_name] = asyncio.create_task(run_simulation(channel_name, pace))
    return {"status": "started", "channel": channel_name, "steps": len(SIM_SCRIPT_ML), "pace_s": pace}


# ----------------------------------------------------------------------------- LLM tool webhooks
@app.post("/tools/triage")
async def tools_triage(request: Request, channel: str | None = Query(None),
                       x_syncup_key: str | None = Header(None)):
    _check_webhook_secret(x_syncup_key)
    args = await _tool_args(request)
    ch = _channel(channel, args)
    return await _graceful(ch, "triage", run_triage(ch, args))


@app.post("/tools/propose_action")
async def tools_propose(request: Request, channel: str | None = Query(None),
                        x_syncup_key: str | None = Header(None)):
    _check_webhook_secret(x_syncup_key)
    args = await _tool_args(request)
    ch = _channel(channel, args)
    return await _graceful(ch, "propose_critical_action", run_propose(ch, args))


@app.post("/tools/route")
async def tools_route(request: Request, channel: str | None = Query(None),
                      x_syncup_key: str | None = Header(None)):
    _check_webhook_secret(x_syncup_key)
    args = await _tool_args(request)
    ch = _channel(channel, args)
    return await _graceful(ch, "finalize_english_brief", run_route(ch, args, via="voice"))


@app.post("/tools/engineer_ack")
async def tools_engineer_ack(request: Request, channel: str | None = Query(None),
                             x_syncup_key: str | None = Header(None)):
    _check_webhook_secret(x_syncup_key)
    args = await _tool_args(request)
    ch = _channel(channel, args)
    return await _graceful(ch, "acknowledge_escalation", run_engineer_ack(ch, args))
