"""Backend verification (Milestone 4: HITL approval + per-language prosody). Run from repo root:
    backend\\.venv\\Scripts\\python.exe backend\\test_backend.py
No network calls: Agora /join and /speak are stubbed; the LLM tool webhooks are simulated."""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
sys.stdout.reconfigure(encoding="utf-8", errors="replace")  # Malayalam/Kannada output on cp1252 consoles

from fastapi.testclient import TestClient  # noqa: E402

import agora_convo  # noqa: E402
import agora_tokens  # noqa: E402
import phonetics  # noqa: E402
import re  # noqa: E402
import main  # noqa: E402
import settings  # noqa: E402

CH = "syncup-floor-01"
main._real_start_history_sync = main.start_history_sync
main.start_history_sync = lambda *a, **k: None  # TestClient requests run in throwaway loops: no background pollers
client = TestClient(main.app)  # no `with`: lifespan (live Murf lookup) intentionally not run
HDR = {"X-SyncUp-Key": settings.WEBHOOK_SECRET} if settings.WEBHOOK_SECRET else {}
passed = 0


def check(name: str, cond: bool, detail: str = "") -> None:
    global passed
    if not cond:
        print(f"  FAIL  {name}  {detail}")
        sys.exit(1)
    passed += 1
    print(f"  PASS  {name}")


def state_of(ch: str) -> dict:
    return client.get(f"/api/session/{ch}/state").json()


def logs_of(ch: str) -> list[str]:
    return [f"[{l['source']}] {l['message']}" for l in state_of(ch)["logs"]]


print("== 1. health, languages & initial state")
r = client.get("/health")
check("/health 200", r.status_code == 200, r.text)
check("company_context loaded", r.json()["company_context_assets"] == ["GATE-02", "LINE-03"], r.text)
langs = client.get("/api/languages").json()
check("5 languages, ml-IN first", [l["code"] for l in langs] == ["ml-IN", "hi-IN", "kn-IN", "ta-IN", "en-IN"])
check("/api/languages exposes per-environment tuning", langs[0]["tuning"]["stage_noisy"]["vad_threshold"] == 0.65)
s = state_of(CH)
check("state starts BEFORE_CONTEXT with empty logs", s["status"] == "BEFORE_CONTEXT" and s["logs"] == [], str(s))

print("== 2. /api/session/start defaults to Malayalam (Agora /join stubbed)")
captured: dict = {}


async def fake_start(channel_name, token, language=None, asset_hint=None, environment=None):
    captured["payload"] = agora_convo.build_join_payload(channel_name, token, language, asset_hint, environment)
    return {"agent_id": "agent-test-001", "status": "RUNNING"}


spoken_calls: list[tuple[str, str]] = []


async def fake_speak(agent_id, text, priority="INTERRUPT"):
    spoken_calls.append((agent_id, text))
    return {}


orig_start, orig_missing, orig_speak = agora_convo.start_convo_agent, settings.missing_for_live_agent, agora_convo.speak_agent
agora_convo.start_convo_agent, agora_convo.speak_agent = fake_start, fake_speak
settings.missing_for_live_agent = lambda: []
try:
    r = client.post("/api/session/start", json={"channel_name": CH})
finally:
    agora_convo.start_convo_agent, settings.missing_for_live_agent = orig_start, orig_missing
check("start 200", r.status_code == 200, r.text)
body = r.json()
check("response language ml-IN / uid 1001 / agent id", body["language"] == "ml-IN" and body["uid"] == 1001
      and body["agent_id"] == "agent-test-001", str(body))
check("response exposes live tuning telemetry", body["tuning"] == {
    "temperature": 0.20, "presence_penalty": 0.15, "voice": body["tuning"]["voice"], "style": "Conversational",
    "rate": -8, "pitch": -2, "volume_offset": -4, "vad_threshold": 0.65, "interrupt_ms": 260, "silence_ms": 680},
      str(body["tuning"]))
p = captured["payload"]["properties"]
check("ARES ml-IN,en-IN (native Malayalam ASR kept)", p["asr"]["vendor"] == "ares"
      and p["asr"]["language"] == "ml-IN,en-IN", str(p["asr"]))
tp = p["tts"]["params"]
check("Murf ml-IN-madhavan / ml-IN / falcon-2.1 / Conversational / rate -8 / pitch -2 / vol -4 (stage) / 24k",
      tp["voiceId"] == "ml-IN-madhavan" and tp["locale"] == "ml-IN" and tp["model"] == "falcon-2.1"
      and tp["style"] == "Conversational" and tp["rate"] == -8 and tp["pitch"] == -2 and tp["volume_offset"] == -4
      and tp["sample_rate"] == 24000, str({k: tp[k] for k in tp if k != "api_key"}))
check("anti-echo payload: SAL speaker lock + interruption=start_of_speech + VAD 0.65/260/650/680 (current v2 schema)",
      p["advanced_features"]["enable_sal"] is True and p["sal"] == {"sal_mode": "locking"}
      and p["interruption"] == {"enable": True, "mode": "start_of_speech"}
      and p["turn_detection"]["config"]["speech_threshold"] == 0.65
      and p["turn_detection"]["config"]["start_of_speech"]["vad_config"]["interrupt_duration_ms"] == 260
      and p["turn_detection"]["config"]["start_of_speech"]["vad_config"]["prefix_padding_ms"] == 650
      and p["turn_detection"]["config"]["end_of_speech"]["vad_config"]["silence_duration_ms"] == 680, str({k: p.get(k) for k in ("sal", "interruption")}))
check("Malayalam Unicode greeting", p["llm"]["greeting_message"]
      == "നമസ്കാരം! സിങ്ക് അപ്പ് ആണ് സംസാരിക്കുന്നത്. ഫ്ലോറിൽ എന്താണ് പ്രശ്നം എന്ന് പറയാമോ?")
sysmsg = p["llm"]["system_messages"][0]["content"]
check("prompt: Malayalam script incl. loanwords, no hyphen suffixes, human codes, < 20 words",
      "Malayalam Unicode script" in sysmsg and "never Roman/Manglish" in sysmsg and "ഗിയർബോക്സ്" in sysmsg
      and "NEVER attach a Malayalam suffix" in sysmsg and "ഇ സീറോ ഫോർ എറർ" in sysmsg
      and "ടിക്കറ്റ് നമ്പർ വൺ സീറോ ഫോർ" in sysmsg and "maximum 15 words" in sysmsg and "ENGLISH" in sysmsg)
check("prompt: warm persona + call flow + speak codes like a person",
      "friendly senior maintenance lead" in sysmsg and "HOW THE CALL FLOWS" in sysmsg
      and "SPEAKING CODES LIKE A PERSON" in sysmsg and "Never read record IDs" in sysmsg
      and "never like a machine" in sysmsg and "calling the engineer" in sysmsg)
check("prompt: HITL — propose first, finalize only after explicit yes",
      "propose_critical_action" in sysmsg and "PROPOSE, DON'T ACT" in sysmsg
      and "Never call finalize_english_brief before an explicit yes" in sysmsg and "'അതെ'" in sysmsg)
s = state_of(CH)
check("state BEFORE_CONTEXT with LINE-03 history (LOG-891) pre-loaded", s["status"] == "BEFORE_CONTEXT"
      and s["asset_context"]["maintenance_logs"][0]["log_id"] == "LOG-891", str(s.get("asset_context")))
msgs = logs_of(CH)
check("[RTC] join log", any(m.startswith("[RTC] Agent joined") and "in Malayalam (ml-IN)" in m for m in msgs), str(msgs))
check("[TTS] PROSODY telemetry log", any(m.startswith("[TTS] PROSODY ml-IN: LLM") and "temp 0.20" in m
                                         and "rate -8 pitch -2 vol -4" in m for m in msgs), str(msgs))
check("[ASR] VAD telemetry log", any(m.startswith("[ASR] ARES ml-IN,en-IN") and "VAD 0.65 / silence 680ms / barge-in 260ms"
                                     in m for m in msgs), str(msgs))

print("== 2b. unique channel per call + zombie-agent teardown + one-click cleanup")
stopped_ids: list[str] = []


async def fake_stop_agent(agent_id):
    stopped_ids.append(agent_id)
    return {"agent_id": agent_id}


join_n = {"n": 0}


async def fake_start2(channel_name, token, language=None, asset_hint=None, environment=None):
    join_n["n"] += 1
    return {"agent_id": f"agent-auto-{join_n['n']}", "status": "RUNNING"}


saved = agora_convo.start_convo_agent, agora_convo.stop_convo_agent, settings.missing_for_live_agent
agora_convo.start_convo_agent, agora_convo.stop_convo_agent = fake_start2, fake_stop_agent
settings.missing_for_live_agent = lambda: []
try:
    main.store.active_agents.clear()
    main.store.register_agent("agent-zombie", "old-channel", "worker")  # an earlier call that never left
    client.post("/api/session/qr-lobby/context", json={"asset_id": "LINE-03", "source": "qr"})
    r1 = client.post("/api/session/start", json={"channel_name": "auto", "previous_channel": "qr-lobby"}).json()
    r2 = client.post("/api/session/start", json={}).json()
    check("channel 'auto'/empty -> fresh unique syncup-<ms> channel each call",
          r1["channel_name"].startswith("syncup-") and r1["channel_name"][7:].isdigit()
          and r1["channel_name"] != r2["channel_name"] and r2["channel_name"].startswith("syncup-"), f"{r1['channel_name']} {r2['channel_name']}")
    check("zombie guard: old agents stopped before each /join (never two agents at once)",
          stopped_ids[:2] == ["agent-zombie", "agent-auto-1"] and list(main.store.active_agents) == ["agent-auto-2"], str(stopped_ids))
    check("QR context carried from the lobby channel into the new call channel",
          state_of(r1["channel_name"])["asset_context"]["source"] == "qr")
    check("[RTC] zombie guard log", any("Zombie guard: stopped 1 previous agent" in l["message"] for l in state_of(r2["channel_name"])["logs"]))
    main.store.register_agent("agent-eng-z", r2["channel_name"] + "-eng", "engineer")
    r = client.post("/api/session/cleanup").json()
    check("POST /api/session/cleanup stops every active agent", r["count"] == 2 and not main.store.active_agents
          and {"agent-auto-2", "agent-eng-z"} <= set(stopped_ids), str(r))
finally:
    agora_convo.start_convo_agent, agora_convo.stop_convo_agent, settings.missing_for_live_agent = saved
    main.store.active_agents.clear()

print("== 3. /tools/triage — LINE-03 gearbox guess (BEFORE -> DURING)")
r = client.post(f"/tools/triage?channel={CH}", headers=HDR, json={
    "asset_id": "LINE-03",
    "verified_facts": ["Machine stopped", "Error E-04 on panel"],
    "worker_guesses": ["Main gearbox burned out"],
    "missing_unknowns": ["Check thermal relay LED"],
    "fault_code": "",
})
b = r.json()
check("triage 200", r.status_code == 200, r.text)
check("db_matched", b["db_matched"] is True, r.text)
base_directive = b["directive"].split(" If you mention")[0]
check("directive is human: describes the record (no LOG id), < 40 words, asks Panel B",
      len(base_directive.split()) < 40 and "LOG-" not in b["directive"] and "6 days ago" in base_directive
      and "newly replaced and healthy" in base_directive and "Panel B" in base_directive, b["directive"])
check("ml-IN triage gives only the error code's spoken form",
      b["spoken_codes"] == {"E-04": "ഇ സീറോ ഫോർ"} and "say it as 'ഇ സീറോ ഫോർ'" in b["directive"]
      and any("Never read record IDs" in n for n in b["speech_notes"]), str(b))
print(f"        directive -> {b['directive']!r}  ({b['elapsed_ms']} ms)")
check("webhook < 300ms", b["elapsed_ms"] < 300, str(b["elapsed_ms"]))
check("status BEFORE_CONTEXT -> INVESTIGATING on first triage", state_of(CH)["status"] == "INVESTIGATING")
if settings.WEBHOOK_SECRET:
    r = client.post(f"/tools/triage?channel={CH}", json={"asset_id": "LINE-03"})
    check("webhook rejects missing X-SyncUp-Key", r.status_code == 401, r.text)

print("== 4. epistemic state + logs after triage")
s = state_of(CH)
d = s["debunked_claims"]
check("gearbox guess debunked by LOG-891", d and d[0]["text"] == "Main gearbox burned out"
      and d[0]["log_id"] == "LOG-891" and "Newly Replaced" in d[0]["evidence"], str(d))
check("guess removed from unverified", s["unverified_guesses"] == [], str(s["unverified_guesses"]))
check("facts + unknown recorded", [f["text"] for f in s["verified_facts"]] == ["Machine stopped", "Error E-04 on panel"]
      and s["missing_unknowns"][0]["text"] == "Check thermal relay LED")
msgs = logs_of(CH)
check("[TRIAGE] extract log", any(m.startswith("[TRIAGE] Extracted 2 facts, 1 guess") for m in msgs), str(msgs))
check("[DB] DEBUNKED log cites LOG-891",
      any(m.startswith("[DB] DEBUNKED: 'Main gearbox burned out' contradicted by LOG-891") for m in msgs), str(msgs))
check("log schema", all(set(l) == {"id", "ts", "level", "source", "message"} for l in s["logs"])
      and all(l["level"] in ("INFO", "WARN", "ACTION") for l in s["logs"]))

print("== 5. Agora-style wrapped args + GATE-02 server guess")
r = client.post("/tools/triage", headers=HDR, json={
    "channel": "syncup-gate-02",
    "arguments": '{"asset_id": "GATE-02", "verified_facts": ["Scanner screen is dead"], '
                 '"worker_guesses": ["Server down hai shayad", "Cable loose ho sakta hai"], "fault_code": ""}',
})
b = r.json()
check("GATE-02 server debunked via LOG-904", b["debunked"] and b["debunked"][0]["log_id"] == "LOG-904", r.text)
check("channel without language gets no phonetic fields", "spoken_codes" not in b and "Say codes as" not in b["directive"])
g = state_of("syncup-gate-02")
check("cable guess stays unverified", [x["text"] for x in g["unverified_guesses"]] == ["Cable loose ho sakta hai"])

print("== 6. CONFIRM gate: finalize before approval is held; voice 'yes' routes")
r = client.post(f"/tools/route?channel={CH}", headers=HDR, json={"summary": "", "priority": ""})
rb = r.json()
check("finalize without proposal -> approval_required (server-side HITL gate)", r.status_code == 200
      and rb["status"] == "approval_required" and state_of(CH)["status"] == "AWAITING_APPROVAL", str(rb))
ticket = rb["ticket_id"]
want_q = f"ശരി, മനസ്സിലായി. ടിക്കറ്റ് നമ്പർ {phonetics.speak_ticket(ticket, 'ml-IN')} ക്രിയേറ്റ് ചെയ്ത് തെർമൽ റിലേ റിസർവ് ചെയ്യട്ടെ?"
check("proposal asks the Malayalam confirmation question", rb["confirmation_question"] == want_q
      and want_q in rb["directive"] and "finalize_english_brief" in rb["directive"], rb["confirmation_question"])
r = client.post(f"/tools/propose_action?channel={CH}", headers=HDR, json={"summary": "Line 3 E-04 thermal relay trip",
                                                                         "priority": "P1"})
pb = r.json()
s = state_of(CH)
check("propose_action keeps the same ticket id, AWAITING_APPROVAL, proposed_ticket TR-882",
      pb["ticket_id"] == ticket and s["status"] == "AWAITING_APPROVAL"
      and "TR-882" in s["proposed_ticket"]["spare_part_reserved"] and s["english_brief"] is None, str(pb))
check("state carries the confirmation question for the approval card", s["confirmation_question"] == want_q)
check("proposal resolves the answered check", s["active_check"] is None and all(u.get("resolved") for u in s["missing_unknowns"]))
check("[ROUTE] approval-gate log", any("APPROVAL GATE: proposed " + ticket in m for m in logs_of(CH)))
r = client.post(f"/tools/route?channel={CH}", headers=HDR, json={"summary": "Line 3 E-04 thermal relay trip",
                                                                 "priority": "P1"})
rb = r.json()
check("voice 'yes' -> finalize routes", rb["status"] == "routed" and rb["ticket_id"] == ticket, str(rb))
check("ml-IN route: ticket spoken as its number only, announces the engineer call, UI keeps exact code",
      rb["ticket_id_spoken"] == "വൺ സീറോ ഫോർ" and ticket not in rb["spoken_line"] and "സിങ്ക്" not in rb["spoken_line"]
      and rb["spoken_line"].startswith("നന്ദി. ടിക്കറ്റ് നമ്പർ വൺ സീറോ ഫോർ") and "എഞ്ചിനീയറെ വിളിച്ച്" in rb["spoken_line"]
      and any("Never read the spare part code" in n for n in rb["speech_notes"]), str(rb))
s = state_of(CH)
brief = s["english_brief"]
check("status ROUTED + brief + follow-up", s["status"] == "ROUTED" and brief["ticket_id"] == ticket
      and s["follow_up_schedule"] == "Automated Murf ml-IN voice check-in scheduled in 30 mins"
      and brief["approved_via"] == "voice" and s["approval"]["via"] == "voice" and s["proposed_ticket"] is None)
check("P1 / TR-882 / Electrical & Controls", brief["priority"] == "P1" and "TR-882" in brief["spare_part_reserved"]
      and brief["assigned_team"] == "Electrical & Controls Maintenance", str(brief))
check("[ROUTE] approved ticket log + follow-up log", any("APPROVED (worker voice)" in m and f"Created Ticket {ticket}" in m
                                                         for m in logs_of(CH))
      and any(m.startswith("[TTS] FOLLOW-UP: Automated Murf ml-IN") for m in logs_of(CH)))
r = client.post(f"/tools/route?channel={CH}", headers=HDR, json={})
check("finalize is idempotent after routing", r.json()["ticket_id"] == ticket and state_of(CH)["status"] == "ROUTED")
print(f"        ticket -> {brief['ticket_id']} | {brief['priority']} | {brief['recommended_action']}")

print("== 7. manual 'Approve & Route Now' + ERROR_HANDLED")
r = client.post("/api/session/syncup-gate-02/approve")
check("approve with nothing pending -> 409", r.status_code == 409, r.text)
client.post("/tools/propose_action?channel=syncup-gate-02", headers=HDR, json={"summary": "Gate 2 scanner dead", "priority": "P2"})
main_state = main.store._states["syncup-gate-02"]
main_state["agent_id"], main_state["language"] = "agent-gate", "kn-IN"  # live Kannada call
r = client.post("/api/session/syncup-gate-02/approve")
g = state_of("syncup-gate-02")
check("manual approve routes via supervisor button", r.status_code == 200 and g["status"] == "ROUTED"
      and g["english_brief"]["approved_via"] == "manual" and "POE-24V" in g["english_brief"]["spare_part_reserved"])
check("manual approve makes the live agent say the Kannada confirmation via /speak",
      spoken_calls and spoken_calls[-1][0] == "agent-gate" and spoken_calls[-1][1].startswith("ಧನ್ಯವಾದ. ಟಿಕೆಟ್ ನಂಬರ್ ಒನ್ ")
      and "ಎಂಜಿನಿಯರ್" in spoken_calls[-1][1] and len(spoken_calls[-1][1].encode()) <= 512, str(spoken_calls))
check("follow-up uses the Kannada Murf locale", g["follow_up_schedule"] == "Automated Murf kn-IN voice check-in scheduled in 30 mins")
agora_convo.speak_agent = orig_speak
orig_triage = main.run_triage


async def boom(ch, args):
    raise RuntimeError("db offline")


main.run_triage = boom
try:
    r = client.post("/tools/triage?channel=err-ch", headers=HDR, json={"asset_id": "LINE-03"})
finally:
    main.run_triage = orig_triage
e = state_of("err-ch")
check("tool failure -> ERROR_HANDLED + graceful spoken retry, never a 500", r.status_code == 200
      and r.json()["status"] == "error_handled" and e["status"] == "ERROR_HANDLED"
      and any("ERROR HANDLED in triage" in l["message"] for l in e["logs"]), r.text)
client.post("/tools/triage?channel=err-ch", headers=HDR, json={"asset_id": "LINE-03", "verified_facts": ["Line 3 stopped"]})
check("next good triage recovers ERROR_HANDLED -> INVESTIGATING", state_of("err-ch")["status"] == "INVESTIGATING")

print("== 8. QR scan pre-loads context (BEFORE)")
r = client.post("/api/session/qr-ch/context", json={"asset_id": "LINE-03", "source": "qr"})
q = state_of("qr-ch")
check("QR context: Bosch Pack-400 + LOG-891 history, BEFORE_CONTEXT", r.status_code == 200
      and r.json()["asset_name"] == "Bosch Pack-400 Packaging Line" and q["status"] == "BEFORE_CONTEXT"
      and q["asset_context"]["source"] == "qr" and q["asset_context"]["maintenance_logs"][0]["log_id"] == "LOG-891")
check("[DB] BEFORE context log", any(l["message"].startswith("BEFORE: context loaded via QR -> LINE-03") for l in q["logs"]))
check("/api/assets/GATE-02 lookup + unknown 404", client.get("/api/assets/GATE-02").json()["maintenance_logs"][0]["log_id"]
      == "LOG-904" and client.get("/api/assets/NOPE").status_code == 404)

print("== 9. per-language calibration injected into the /join payload")
WANT = {  # language: (temperature, presence, rate, pitch, base silence, base threshold, base interrupt)
    "ml-IN": (0.20, 0.15, -8, -2, 680, 0.55, 180),
    "kn-IN": (0.22, 0.15, -5, 0, 680, 0.55, 180),
    "hi-IN": (0.35, 0.25, 0, 0, 580, 0.53, 170),
    "ta-IN": (0.22, 0.15, -6, -1, 660, 0.55, 180),
    "en-IN": (0.30, 0.20, 3, -1, 520, 0.52, 160),
}
for code, (temp, pres, rate, pitch, sil, thr, intr) in WANT.items():
    prof = agora_convo.LANGUAGE_PROFILES[code]
    for env in ("quiet", "stage_noisy"):
        pp = agora_convo.build_join_payload("c", "t", code, "GATE-02", env)["properties"]
        cfg, tts, llm = pp["turn_detection"]["config"], pp["tts"]["params"], pp["llm"]["params"]
        stage = env == "stage_noisy"
        want_thr = round(min(0.72, thr + 0.10), 2) if stage else thr
        ok = (llm["temperature"] == temp and llm["presence_penalty"] == pres and llm["max_tokens"] == 110
              and tts["rate"] == rate and tts["pitch"] == pitch and tts["style"] == "Conversational"
              and tts["locale"] == prof["tts_params"]["locale"] and tts["model"] == "falcon-2.1"
              and cfg["end_of_speech"]["vad_config"]["silence_duration_ms"] == sil
              and cfg["speech_threshold"] == want_thr
              and cfg["start_of_speech"]["vad_config"]["interrupt_duration_ms"] == intr + (80 if stage else 0)
              and tts.get("volume_offset") == -4
              and pp["asr"]["language"] == prof["asr_language"] and pp["llm"]["greeting_message"] == prof["greeting"])
        check(f"{code}/{env}: temp {temp} rate {rate:+d} pitch {pitch:+d} silence {sil} VAD {want_thr}", ok,
              str({"llm": llm, "tts": {k: v for k, v in tts.items() if k != "api_key"}, "vad": cfg}))
check("Dravidian (ml/kn/ta) cooler + slower + more patient than hi/en",
      max(WANT[c][0] for c in ("ml-IN", "kn-IN", "ta-IN")) < min(WANT[c][0] for c in ("hi-IN", "en-IN"))
      and max(WANT[c][2] for c in ("ml-IN", "kn-IN", "ta-IN")) < min(WANT[c][2] for c in ("hi-IN", "en-IN"))
      and min(WANT[c][4] for c in ("ml-IN", "kn-IN", "ta-IN")) > max(WANT[c][4] for c in ("hi-IN", "en-IN")))
check("native-script greetings (kn/hi/ta)", "ನಮಸ್ಕಾರ" in agora_convo.LANGUAGE_PROFILES["kn-IN"]["greeting"]
      and "नमस्ते" in agora_convo.LANGUAGE_PROFILES["hi-IN"]["greeting"]
      and "வணக்கம்" in agora_convo.LANGUAGE_PROFILES["ta-IN"]["greeting"])
check("kn/ta voices fall back to native (ml-IN-madhavan lacks kn-IN/ta-IN)",
      agora_convo.LANGUAGE_PROFILES["kn-IN"]["tts_params"]["voiceId"] == "kn-IN-harshitha"
      and agora_convo.LANGUAGE_PROFILES["ta-IN"]["tts_params"]["voiceId"] == "ta-IN-karthikeyan")
check("soft_voice lowers VAD within floor", agora_convo.compute_tuning("ml-IN", "soft_voice")["vad_threshold"] == 0.42)
check("RTM transcripts: enable_rtm + data_channel rtm + metrics", p["advanced_features"]["enable_rtm"] is True
      and p["parameters"]["data_channel"] == "rtm" and p["parameters"]["enable_metrics"] is True)
check("agent uid 999999, remote 1001", p["agent_rtc_uid"] == "999999" and p["remote_rtc_uids"] == ["1001"])
tools = p["llm"]["tools"]
check("3 sync POST server tools (triage, propose, finalize) carrying channel",
      [t["function"]["name"] for t in tools] == ["triage_and_verify_claim", "propose_critical_action", "finalize_english_brief"]
      and p["advanced_features"]["enable_tools"] is True and tools[1]["server"]["url"].split("?")[0].endswith("/tools/propose_action")
      and all(t["server"]["method"] == "POST" and f"channel={CH}" in t["server"]["url"]
              and t["execution"]["mode"] == "sync" for t in tools))
check("tool bodies use only whole {{args.*}} placeholders",
      all(v.startswith("{{") and v.endswith("}}") for t in tools for v in t["server"]["body"].values()))

print("== 10. AccessToken2 (007) RTC+RTM token builder (offline)")
import base64, hashlib, hmac, struct, zlib  # noqa: E401,E402


def verify_007(token: str, app_id: str, cert: str) -> tuple[bool, list[int]]:
    """Independent decoder: re-derive the HMAC exactly as Agora's AccessToken2.verify_signature does."""
    buf = zlib.decompress(base64.b64decode(token[3:]))
    n = struct.unpack("<H", buf[:2])[0]
    sig, info = buf[2:2 + n], buf[2 + n:]
    alen = struct.unpack("<H", info[:2])[0]
    issue_ts, _exp, salt = struct.unpack("<III", info[2 + alen:14 + alen])
    k = hmac.new(struct.pack("<I", issue_ts), cert.encode(), hashlib.sha256).digest()
    k = hmac.new(struct.pack("<I", salt), k, hashlib.sha256).digest()
    ok = hmac.compare_digest(sig, hmac.new(k, info, hashlib.sha256).digest()) and info[2:2 + alen] == app_id.encode()
    rest = info[14 + alen:]
    count = struct.unpack("<H", rest[:2])[0]
    services, rest = [], rest[2:]
    for _ in range(count):
        stype = struct.unpack("<H", rest[:2])[0]
        services.append(stype)
        np_ = struct.unpack("<H", rest[2:4])[0]
        rest = rest[4 + 6 * np_:]
        for _s in range(2 if stype == 1 else 1):  # RTC: channel + uid strings, RTM: user id
            ln = struct.unpack("<H", rest[:2])[0]
            rest = rest[2 + ln:]
    return ok, services


orig = settings.AGORA_APP_ID, settings.AGORA_APP_CERTIFICATE
try:
    settings.AGORA_APP_ID, settings.AGORA_APP_CERTIFICATE = "970CA35de60c44645bbae8a215061b33", "5CFd2fd1755d40ecb72977518be15d3b"
    t = agora_tokens.build_session_tokens(CH)
    check("007 tokens for user + agent", t["user_rtc_token"].startswith("007") and t["agent_rtc_token"].startswith("007")
          and t["user_rtm_token"] == t["user_rtc_token"])
    ok, services = verify_007(t["agent_rtc_token"], settings.AGORA_APP_ID, settings.AGORA_APP_CERTIFICATE)
    check("signature verifies and token carries RTC(1) + RTM(2) services", ok and services == [1, 2], str(services))
    check("wrong certificate fails verification", not verify_007(t["agent_rtc_token"], settings.AGORA_APP_ID, "0" * 32)[0])
    settings.AGORA_APP_CERTIFICATE = ""
    check("App-ID-only mode -> empty tokens", agora_tokens.build_session_tokens(CH)["user_rtc_token"] == "")
finally:
    settings.AGORA_APP_ID, settings.AGORA_APP_CERTIFICATE = orig

print("== 11. GET /api/preflight")
main._http = None  # pooled client must belong to this event loop
with TestClient(main.app) as warm_client:  # runs the real lifespan: startup warm-up, like the live server
    r = warm_client.get("/api/preflight")
    pf = r.json()
    pf2 = warm_client.get("/api/preflight").json()
main._http = None
check("preflight 200 with all keys", r.status_code == 200 and {"agora_creds", "murf_api", "webhook_tunnel", "ready"} <= set(pf), r.text)
check(f"preflight cold < 2.5s ({pf['elapsed_ms']} ms), warm < 1.5s ({pf2['elapsed_ms']} ms)",
      pf["elapsed_ms"] < 2500 and pf2["elapsed_ms"] < 1500)
check(f"murf_api status reported ({pf['murf_api']})", pf["murf_api"] in ("OK", "AUTH_ERROR", "SLOW", "UNREACHABLE", "MISSING_KEY") and isinstance(pf["agora_creds"], bool))
if not settings.PUBLIC_WEBHOOK_BASE_URL.startswith("https://"):
    check("localhost tunnel flagged INVALID_TUNNEL", pf["webhook_tunnel"] == "INVALID_TUNNEL" and not pf["ready"])

print("== 12. POST /api/session/test-ch/simulate steps through all 4 stages")
seen: list[str] = []
orig_publish = main.store._publish


demo_seen: list[str] = []


def spy(channel, snapshot):
    if channel == "test-ch" and (not seen or seen[-1] != snapshot["status"]):
        seen.append(snapshot["status"])
    if channel == "test-ch" and (not demo_seen or demo_seen[-1] != snapshot["demo_stage"]):
        demo_seen.append(snapshot["demo_stage"])
    orig_publish(channel, snapshot)


main.store._publish = spy
try:
    r = client.post("/api/session/test-ch/simulate?pace=0&wait=true")
finally:
    main.store._publish = orig_publish
check("simulate completes", r.status_code == 200 and r.json()["status"] == "completed", r.text)
check(f"stage sequence {seen}", seen == ["BEFORE_CONTEXT", "INVESTIGATING", "AWAITING_APPROVAL", "ROUTED"], str(seen))
check(f"demo flow {demo_seen}", demo_seen == ["WORKER_CALL", "ENGINEER_RINGING", "ENGINEER_CONNECTED", "DISPATCH_CONFIRMED"], str(demo_seen))
s = state_of("test-ch")
check("sim routed a ticket via voice approval", s["status"] == "ROUTED" and s["english_brief"]["assigned_team"]
      == "Electrical & Controls Maintenance" and s["english_brief"]["priority"] == "P1"
      and s["english_brief"]["approved_via"] == "voice", str(s["english_brief"]))
check("sim follow-up scheduled", s["follow_up_schedule"] == "Automated Murf ml-IN voice check-in scheduled in 30 mins")
check("sim QR context + debunked gearbox via LOG-891", s["asset_context"]["source"] == "qr"
      and any(d["log_id"] == "LOG-891" for d in s["debunked_claims"]))
check("sim transcripts: 8 Malayalam turns incl. confirmation, yes and the engineer ETA", len(s["transcripts"]) == 8
      and {t["role"] for t in s["transcripts"]} == {"worker", "agent"} and s["language"] == "ml-IN"
      and "റിസർവ് ചെയ്യട്ടെ?" in s["transcripts"][4]["text"] and s["transcripts"][5]["text"] == "അതെ, ചെയ്യൂ."
      and s["transcripts"][-1]["text"].startswith("എഞ്ചിനീയർ പത്ത് മിനിറ്റിനുള്ളിൽ"),
      str([t["text"] for t in s["transcripts"]]))
e = s["escalation"]
check("sim outbound English call: Arjun, completed, accepted, ETA 10, 3 caption turns", e["status"] == "completed"
      and e["engineer"]["name"] == "Arjun M." and e["accepted"] is True and e["eta_minutes"] == 10
      and [t["role"] for t in e["transcripts"]] == ["agent", "engineer", "agent"], str(e))
check("engineer opener = spec greeting, codes in spoken form", e["opener"] == ("Hi Arjun, SyncUp Dispatch here. Line three "
      "stopped with E zero four. Gearbox is fine; Panel B thermal relay tripped. Part T R eight eight two is reserved. "
      "Confirming dispatch?"), e["opener"])
check("sim demo_stage ends DISPATCH_CONFIRMED", s["demo_stage"] == "DISPATCH_CONFIRMED")
srcs = {l["source"] for l in s["logs"]}
check("sim logs cover RTC/ASR/TTS/TRIAGE/DB/ROUTE", {"RTC", "ASR", "TTS", "TRIAGE", "DB", "ROUTE"} <= srcs, str(srcs))
check("routed agent line speaks the ticket number naturally",
      "ടിക്കറ്റ് നമ്പർ " + phonetics.speak_ticket(s["english_brief"]["ticket_id"], "ml-IN") in s["transcripts"][6]["text"]
      and s["english_brief"]["ticket_id"] not in s["transcripts"][6]["text"])
agent_lines = [t["text"] for t in s["transcripts"] if t["role"] == "agent"]
check("sim agent lines obey TTS rules (no Latin letters/digits with hyphen suffix, no raw codes)",
      not any(re.search(r"[A-Za-z0-9]-[ഀ-ൿ]", t) or phonetics.find_codes(t) for t in agent_lines), str(agent_lines))
check("routing closes the investigation (unknowns resolved, no open check)",
      s["active_check"] is None and all(u.get("resolved") for u in s["missing_unknowns"]))

print("== 13. engineer outbound call: ring -> green answer -> briefing -> confirm (Agora stubbed)")
import asyncio  # noqa: E402

eng_captured: dict = {}


async def fake_eng_start(channel_name, token, source_channel, eng, briefing, environment=None, language="en-IN"):
    eng_captured["payload"] = agora_convo.build_engineer_join_payload(channel_name, token, source_channel, eng, briefing,
                                                                      environment, language)
    eng_captured["channel"] = channel_name
    return {"agent_id": "agent-eng-001", "status": "RUNNING"}


r = client.post("/api/engineer/answer", json={"channel_name": "nothing-routed"})
check("answer before any routed incident -> 409", r.status_code == 409, r.text)
check("routing rang the engineer: demo_stage ENGINEER_RINGING + engineer_brief",
      state_of(CH)["demo_stage"] == "ENGINEER_RINGING" and state_of(CH)["engineer_brief"]["engineer"]["name"] == "Arjun M.")
orig_eng, orig_speak2, orig_stop = agora_convo.start_engineer_agent, agora_convo.speak_agent, agora_convo.stop_convo_agent
agora_convo.start_engineer_agent, agora_convo.speak_agent = fake_eng_start, fake_speak
stopped2: list[str] = []


async def fake_stop(agent_id):
    stopped2.append(agent_id)
    return {"agent_id": agent_id}


agora_convo.stop_convo_agent = fake_stop
settings.missing_for_live_agent = lambda: []
main.start_history_sync = lambda *a, **k: None  # no background poller inside TestClient
try:
    main.store.register_agent("agent-test-001", CH, "worker")  # the worker call is still live
    main.store._states[CH]["agent_id"] = "agent-test-001"
    r = client.post("/api/engineer/answer", json={"channel_name": CH})
    eb = r.json()
    st = state_of(CH)
    check("green Answer: worker agent stopped first, engineer agent on a fresh syncup-eng-<ms> channel",
          r.status_code == 200 and stopped2 == ["agent-test-001"] and eb["channel_name"].startswith("syncup-eng-")
          and eb["agent_id"] == "agent-eng-001" and st["demo_stage"] == "ENGINEER_CONNECTED" and st["agent_id"] is None
          and list(main.store.active_agents) == ["agent-eng-001"], r.text)
    ep = eng_captured["payload"]["properties"]
    want_greet = ("Hi Arjun, SyncUp Dispatch here. Line three stopped with E zero four. Gearbox is fine; Panel B thermal "
                  "relay tripped. Part T R eight eight two is reserved. Confirming dispatch?")
    check("engineer agent speaks first with the spec greeting (en-IN, Murf en-IN-aarav)",
          ep["llm"]["greeting_message"] == want_greet and eb["greeting"] == want_greet and ep["asr"]["language"] == "en-IN"
          and ep["tts"]["params"]["voiceId"] == "en-IN-aarav" and "OUTBOUND phone call" in ep["llm"]["system_messages"][0]["content"]
          and "maximum 15 words" in ep["llm"]["system_messages"][0]["content"], ep["llm"]["greeting_message"])
    check("engineer agent: SAL lock + Murf pronunciation dictionary + lenient chunking",
          ep["advanced_features"]["enable_sal"] is True and ep["tts"]["params"]["predictive_chunking"] == "lenient"
          and ep["tts"]["params"]["pronunciation_dictionary"]["TR-882"]["pronunciation"] == "T R eight eight two")
    et = ep["llm"]["tools"]
    check("engineer tool acknowledge_escalation -> /tools/engineer_ack on the worker channel",
          [t["function"]["name"] for t in et] == ["acknowledge_escalation"]
          and et[0]["server"]["url"].endswith(f"/tools/engineer_ack?channel={CH}")
          and all(v.startswith("{{") for v in et[0]["server"]["body"].values()))
    spoken_calls.clear()
    r = client.post(f"/tools/engineer_ack?channel={CH}", headers=HDR,
                    json={"eta_minutes": "10", "accepted": "true", "notes": "bringing relay"})
    ab = r.json()
    st = state_of(CH)
    check("voice 'yes, dispatch' -> DISPATCH_CONFIRMED, ETA 10, Malayalam worker update prepared", r.status_code == 200
          and ab["accepted"] is True and st["demo_stage"] == "DISPATCH_CONFIRMED" and st["escalation"]["eta_minutes"] == 10
          and ab["worker_update"].startswith("എഞ്ചിനീയർ പത്ത് മിനിറ്റിനുള്ളിൽ")
          and st["english_brief"]["engineer"]["name"] == "Arjun M." and spoken_calls == [], r.text)
    r = client.post(f"/api/session/{CH}/escalation/end")
    st = state_of(CH)
    check("hang-up: call completed; worker (agent handed over) gets the ETA as an app message", r.json()["status"] == "completed"
          and st["escalation"]["status"] == "completed" and st["transcripts"][-1]["text"].startswith("എഞ്ചിനീയർ"), str(st["transcripts"][-1:]))
    # Malayalam engineer briefing + manual confirm + decline on another channel
    client.post("/tools/triage?channel=eng-ml", headers=HDR, json={"asset_id": "LINE-03", "verified_facts": ["Line 3 stopped"],
                                                                 "worker_guesses": [], "missing_unknowns": [], "fault_code": "E-04"})
    main.store._states["eng-ml"]["language"] = "ml-IN"
    r = client.post("/api/engineer/ring", json={"channel_name": "eng-ml"})
    check("/api/engineer/ring finishes triage (supervisor approval) and rings", r.status_code == 200
          and r.json()["demo_stage"] == "ENGINEER_RINGING" and state_of("eng-ml")["english_brief"]["approved_via"] == "manual", r.text)
    r = client.post("/api/engineer/answer", json={"channel_name": "eng-ml", "language": "ml-IN"})
    ep = eng_captured["payload"]["properties"]
    check("engineer briefing selectable in Malayalam (ARES ml-IN, Malayalam greeting)", r.status_code == 200
          and ep["asr"]["language"] == "ml-IN,en-IN" and ep["llm"]["greeting_message"].startswith("ഹായ് അർജുൻ")
          and "ഡിസ്പാച്ച് ഉറപ്പിക്കട്ടെ?" in ep["llm"]["greeting_message"], ep["llm"]["greeting_message"])
    r = client.post("/api/engineer/confirm", json={"channel_name": "eng-ml"})
    check("Confirm Dispatch button -> DISPATCH_CONFIRMED", r.status_code == 200 and state_of("eng-ml")["demo_stage"] == "DISPATCH_CONFIRMED")
    client.post("/api/engineer/ring", json={"channel_name": "eng-ml"})
    r = client.post("/api/engineer/decline", json={"channel_name": "eng-ml"})
    check("Decline -> back to the worker screen, call cleared", r.json()["demo_stage"] == "WORKER_CALL"
          and state_of("eng-ml")["escalation"] is None)
finally:
    agora_convo.start_engineer_agent, agora_convo.speak_agent, agora_convo.stop_convo_agent = orig_eng, orig_speak2, orig_stop
    settings.missing_for_live_agent = orig_missing
    main.store.active_agents.clear()

print("== 13b. speech normalizer (Murf never hears 'minus')")
import speech_normalizer as sn  # noqa: E402

for code, want_en, want_ml in [("LINE-03", "Line three", "ലൈൻ ത്രീ"), ("Line 3", "Line three", "ലൈൻ ത്രീ"),
                               ("GATE-02", "Gate two", "ഗേറ്റ് ടു"), ("E-04", "E zero four", "ഇ സീറോ ഫോർ"),
                               ("LOG-891", "Log eight nine one", "ലോഗ് എയ്റ്റ് നയൻ വൺ"),
                               ("LOG-904", "Log nine zero four", None), ("SYNC-104", "Sync one zero four", "സിങ്ക് വൺ സീറോ ഫോർ"),
                               ("TR-882", "T R eight eight two", "ടി ആർ എയ്റ്റ് എയ്റ്റ് ടു"), ("POE-24V", "P O E twenty four volt", None)]:
    ok = sn.normalize_for_speech(code, "en-IN") == want_en and (want_ml is None or sn.normalize_for_speech(code, "ml-IN") == want_ml)
    check(f"normalize {code} -> '{want_en}'" + (f" / '{want_ml}'" if want_ml else ""), ok,
          f"{sn.normalize_for_speech(code, 'en-IN')} | {sn.normalize_for_speech(code, 'ml-IN')}")
sent = sn.normalize_for_speech("Line 3 stopped with E-04; ticket SYNC-104 (ticket 104), part TR-882.", "en-IN")
check("sentence: no hyphens or raw codes left", sent == ("Line three stopped with E zero four; ticket Sync one zero four "
      "(ticket one zero four), part T R eight eight two.") and "-" not in sent, sent)
check("Malayalam glossary: gearbox / thermal relay / Panel B in script",
      sn.normalize_for_speech("gearbox, thermal relay, Panel B", "ml-IN") == "ഗിയർബോക്സ്, തെർമൽ റിലേ, പാനൽ ബി")
wp = agora_convo.build_join_payload("c", "t", "ml-IN")["properties"]["tts"]["params"]
check("worker TTS: Murf SAY_AS dictionary (E-04, SYNC-1xx) + predictive_chunking lenient",
      wp["predictive_chunking"] == "lenient" and wp["pronunciation_dictionary"]["E-04"] == {"type": "SAY_AS", "pronunciation": "ഇ സീറോ ഫോർ"}
      and wp["pronunciation_dictionary"]["SYNC-104"]["pronunciation"] == "സിങ്ക് വൺ സീറോ ഫോർ")

import importlib  # noqa: E402

main_mod = importlib.import_module("main")


async def history_case() -> dict:
    calls = {"n": 0}

    async def fake_history(agent_id, client=None):
        calls["n"] += 1
        items = [{"role": "assistant", "content": "നമസ്കാരം!"}, {"role": "user", "content": "Line 3 നിന്നു"}]
        return items[: min(2, calls["n"])]

    orig_hist, main_mod.HISTORY_POLL_S = agora_convo.get_history, 0.01
    agora_convo.get_history = fake_history
    try:
        await main_mod.store.reset("hist-ch", agent_id="agent-h")
        real_sync = main_mod.__dict__.get("_real_start_history_sync")
        await asyncio.sleep(0)
        real_sync("hist-ch", "agent-h", "worker")
        await asyncio.sleep(1.0)  # first poll creates the pooled HTTPS client (~0.3 s cold on Windows)
        main_mod.stop_history_sync("hist-ch:worker")
        return await main_mod.store.get("hist-ch")
    finally:
        agora_convo.get_history = orig_hist


hs = asyncio.run(history_case())
check("REST history sync streams the live chat when RTM captions are missing",
      [(t["role"], t["source"]) for t in hs["transcripts"]] == [("agent", "history"), ("worker", "history")]
      and any(l["id"].startswith("hist-") and l["message"] == "Worker: Line 3 നിന്നു" for l in hs["logs"]), str(hs["transcripts"]))

print("== 14. phonetics speller (ml / kn / ta, hi+en fallback)")
for code, lang, want in [("E-04", "ml-IN", "ഇ സീറോ ഫോർ"), ("SYNC-104", "ml-IN", "സിങ്ക് വൺ സീറോ ഫോർ"),
                         ("LOG-891", "ml-IN", "ലോഗ് എയ്റ്റ് നയൻ വൺ"), ("TR-882", "ml-IN", "ടി ആർ എയ്റ്റ് എയ്റ്റ് ടു"),
                         ("E-04", "kn-IN", "ಇ ಜೀರೋ ಫೋರ್"), ("SYNC-104", "kn-IN", "ಸಿಂಕ್ ಒನ್ ಜೀರೋ ಫೋರ್"),
                         ("E-04", "ta-IN", "இ ஜீரோ ஃபோர்"), ("SYNC-104", "hi-IN", "SYNC 104")]:
    check(f"{code} [{lang}] -> {want}", phonetics.speak(code, lang) == want, phonetics.speak(code, lang))
for code, lang, want in [("SYNC-104", "ml-IN", "വൺ സീറോ ഫോർ"), ("SYNC-104", "en-IN", "one zero four"),
                         ("SYNC-104", "kn-IN", "ಒನ್ ಜೀರೋ ಫೋರ್")]:
    check(f"ticket {code} [{lang}] -> '{want}' (number only)", phonetics.speak_ticket(code, lang) == want)
check("English part code for engineers: TR-882 -> 'T R eight eight two'", phonetics.speak_en("TR-882") == "T R eight eight two")

print(f"\nALL {passed} CHECKS PASSED")
for w in settings.live_warnings():
    print(f"NOTE: {w}")
