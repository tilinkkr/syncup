"""Ground-truth cross-checks against data/company_context.json (pure, synchronous, sub-millisecond)."""
import json
import re

import settings

with open(settings.COMPANY_CONTEXT_PATH, encoding="utf-8") as f:
    COMPANY_CONTEXT: dict = json.load(f)

_HEALTHY = ("HEALTHY", "ONLINE")


def _norm(text: str) -> str:
    return re.sub(r"\s+", " ", text.lower()).strip()


def resolve_asset(asset_id: str | None, texts: list[str]) -> str | None:
    if asset_id:
        key = asset_id.upper().replace("_", "-")
        if key in COMPANY_CONTEXT:
            return key
    blob = _norm(" ".join(texts))
    for key, asset in COMPANY_CONTEXT.items():
        if key.lower() in blob or any(a in blob for a in asset.get("aliases", [])):
            return key
    return None


def find_contradiction(asset_id: str | None, guess: str) -> dict | None:
    """Return the maintenance log that disproves `guess`, or None."""
    if not asset_id:
        return None
    g = _norm(guess)
    for log in COMPANY_CONTEXT[asset_id]["maintenance_logs"]:
        names = [log["component"].lower(), *log.get("component_aliases", [])]
        if any(n in g for n in names) and log["status"].upper().startswith(_HEALTHY):
            return log
    return None


def pick_sop(asset_id: str | None, fault_code: str | None, texts: list[str]):
    """Return (code, rule) for the most relevant SOP, or (None, None)."""
    if not asset_id:
        return None, None
    rules: dict = COMPANY_CONTEXT[asset_id]["sop_rules"]
    if fault_code and fault_code.upper() in rules:
        return fault_code.upper(), rules[fault_code.upper()]
    blob = " ".join(texts).upper()
    for code, rule in rules.items():
        if code in blob:
            return code, rule
    code = next(iter(rules), None)
    return (code, rules[code]) if code else (None, None)


def evidence_string(log: dict) -> str:
    return f"{log['log_id']}: {log['component']} — {log['status']} ({log['date']})"
