# EPISTEMIC_ENGINE.md — SyncUp State & Cross-Check Contract

## Session state (per `channel_name`, `backend/state_store.py`)
```json
{
  "channel": "syncup-floor-01", "agent_id": null,
  "status": "IDLE | INVESTIGATING | ROUTED",
  "asset_id": "LINE-03",
  "verified_facts":    [{"text": "...", "source": "worker"}],
  "unverified_guesses":[{"text": "...", "asset_id": "LINE-03"}],
  "debunked_claims":   [{"text": "...", "evidence": "LOG-891: Main Gearbox — HEALTHY - Newly Replaced (6 days ago)", "log_id": "LOG-891"}],
  "missing_unknowns":  [{"text": "..."}],
  "english_brief": null,
  "updated_at": 1700000000.0
}
```
Every mutation is pushed to subscribers (`GET /api/session/{channel}/stream`, SSE).

## Tools (called by the Agora LLM)
1. `triage_and_verify_claim(asset_id, verified_facts[], worker_guesses[], missing_unknowns[], fault_code?)` → `POST /tools/triage?channel=`
2. `finalize_english_brief(summary?, priority?)` → `POST /tools/route?channel=`

## Cross-check rules (`backend/data/company_context.json`)
- A guess is **debunked** when it mentions a component (or alias) whose maintenance log for that asset is `HEALTHY`/`ONLINE`.
  - `LINE-03` + gearbox → `LOG-891` (Main Gearbox newly replaced 6 days ago).
  - `GATE-02` + server → `LOG-904` (SRV-BLR-01 online 99.98%).
- Otherwise it stays an **unverified guess**.
- Facts are de-duplicated (case-insensitive). Unknowns are de-duplicated.
- The triage response is a < 30-token directive: debunked → state the evidence and ask the SOP check question; else → ask the SOP check question; else → ask about the first unknown.

## English brief (`/tools/route`)
`ticket_id` (`SYNC-1xx`), `priority`, `asset`, `verified_facts`, `debunked_claims`, `unverified_guesses`, `recommended_action`, `spare_part_reserved`, `assigned_team`. Status → `ROUTED`.
Priority: `P1` if the asset is stopped/down, else `P2`.

## Human-in-the-loop approval (Milestone 4)
Stages (`state.status`): `BEFORE_CONTEXT` → `INVESTIGATING` → `AWAITING_APPROVAL` → `ROUTED`, plus `ERROR_HANDLED`.

| Stage | Trigger | State written |
|---|---|---|
| BEFORE_CONTEXT | session start or `POST /api/session/{ch}/context` (QR scan) | `asset_context` (maintenance logs and SOPs for the asset) |
| INVESTIGATING | first `triage_and_verify_claim` | facts, guesses, debunked claims, unknowns |
| AWAITING_APPROVAL | `propose_critical_action` → `POST /tools/propose_action` | `proposed_ticket` (draft brief with the ticket id already assigned) |
| ROUTED | voice "yes" → `finalize_english_brief` (`/tools/route`), or `POST /api/session/{ch}/approve` | `english_brief`, `approval.via`, `follow_up_schedule` |
| ERROR_HANDLED | a tool raised, or Agora `/join` failed | `error`; the agent says the language's `failure` line, and the next good triage recovers |

- **Server-side gate.** `/tools/route` only finalizes when a proposal is pending. If the LLM skips the proposal, the server proposes on its behalf and returns `status: approval_required`.
- **Idempotent finalize.** Calling finalize again after routing returns the same ticket, so a voice "yes" and the Approve button can't race into two tickets.
- **Manual approval speaks.** The Approve button also calls Agora `/agents/{id}/speak`, so the worker hears the routed confirmation in their own language.
