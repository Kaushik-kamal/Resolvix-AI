"""Run: pip install -e contracts/python pytest pyyaml && pytest contracts/tests -q
Every member runs this before integration. It must stay green; a red test means someone drifted from the contract."""
import json
import pathlib

import yaml
from pydantic import TypeAdapter

from resolvix_contracts import CONTRACT_VERSION, TICKET_ID_PLACEHOLDER, speak_ticket_id
from resolvix_contracts.models import (
    BrainEvent, CallContext, CallEnd, CallStart, CallStartPlan, DepartmentsConfig, ErrorEnvelope, GapCluster, GapCreate,
    KBEntry, KBExport, KBSource, KBVersionInfo, SmsRequest, SmsResult, Ticket, TicketCreate, TicketCreated, TicketEvent,
    TicketPatch, TurnRequest, TurnSummary,
)

ROOT = pathlib.Path(__file__).resolve().parents[1]
FX = ROOT / "fixtures"
EV = TypeAdapter(BrainEvent)

OPS = {
    "call_start": CallStart, "call_end": CallEnd, "ticket_create": TicketCreate, "ticket_created": TicketCreated,
    "ticket": Ticket, "ticket_patch": TicketPatch, "ticket_event": TicketEvent, "sms_request": SmsRequest,
    "sms_result": SmsResult, "gap_create": GapCreate, "gap_cluster": GapCluster, "error": ErrorEnvelope,
    "turn_summary": TurnSummary, "call_context": CallContext, "call_start_plan": CallStartPlan,
    "kb_source": KBSource, "kb_version_info": KBVersionInfo,
}


def test_version():
    assert CONTRACT_VERSION == "1.0.0"


def test_ops_fixtures_validate():
    for name, model in OPS.items():
        model.model_validate_json((FX / "ops" / f"{name}.json").read_text())


def test_brain_streams_are_well_formed():
    files = sorted((FX / "brain_streams").glob("*.jsonl"))
    assert len(files) >= 9
    for f in files:
        lines = f.read_text().strip().splitlines()
        TurnRequest.model_validate(json.loads(lines[0])["_request"])
        events = [EV.validate_python(json.loads(line)) for line in lines[1:]]
        assert events[0].type == "meta", f
        assert events[-1].type == "done", f
        assert sum(e.type == "meta" for e in events) == 1, f
        # ticket-first: every transfer must come after a create_ticket in the same turn
        seen_ticket = False
        for e in events:
            if e.type == "action" and e.action.kind == "create_ticket":
                seen_ticket = True
                assert e.blocking, f"create_ticket must be blocking in {f}"
            if e.type == "action" and e.action.kind == "transfer" and e.action.requires_ticket:
                assert seen_ticket, f"transfer before ticket in {f}"
            if e.type == "speech" and TICKET_ID_PLACEHOLDER in e.text:
                assert seen_ticket, f"placeholder spoken before ticket exists in {f}"


def test_kb_samples():
    for line in (ROOT / "kb/sample_kb.jsonl").read_text().splitlines():
        KBEntry.model_validate_json(line)
    KBExport.model_validate_json((ROOT / "kb/sample_kb_export.json").read_text())


def test_config_files():
    deps = DepartmentsConfig.model_validate(yaml.safe_load((ROOT / "config/departments.yaml").read_text()))
    keys = {d.key for d in deps.departments}
    assert deps.default_department in keys and "emergency" in keys
    prefixes = [d.ticket_prefix for d in deps.departments]
    assert len(prefixes) == len(set(prefixes))
    rules = yaml.safe_load((ROOT / "config/urgency_rules.yaml").read_text())
    assert rules["rules"][0]["id"] == "R-SAFETY" and rules["rules"][-1]["when"] == {}
    tpl = yaml.safe_load((ROOT / "config/sms_templates.yaml").read_text())["templates"]
    assert set(tpl) == {"ticket_created", "status_change", "answer_copy", "staff_alert"}


def test_speak_ticket_id():
    assert speak_ticket_id("EX-1042", "en") == "E X, one zero four two"
    assert speak_ticket_id("EX-1042", "hi") == "E X, ek shoonya chaar do"
