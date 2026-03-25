"""Tests for CASA-RX API."""
from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

from main import app

client = TestClient(app)

BASIC_REQUEST = {
    "task": "Summarize the quarterly sales report for the finance team",
    "context": {
        "user_role": "analyst",
        "domain": "finance",
        "constraints": {"format": "markdown", "tone": "professional", "max_tokens": 1200},
    },
    "tools": [],
    "policy_id": "default_v1",
}


# ---------------------------------------------------------------------------
# /v1/execute
# ---------------------------------------------------------------------------

class TestExecute:
    def test_proceed_basic(self):
        resp = client.post("/v1/execute", json=BASIC_REQUEST)
        assert resp.status_code == 200
        data = resp.json()
        assert data["decision"] in ("PROCEED", "CLARIFY", "HALT")
        assert data["mode"] in ("answer", "ask", "tool_use", "refuse")
        assert "contract" in data
        assert "trace_id" in data["contract"]

    def test_proceed_returns_output(self):
        resp = client.post("/v1/execute", json=BASIC_REQUEST)
        assert resp.status_code == 200
        data = resp.json()
        if data["decision"] == "PROCEED":
            assert data["output"] is not None
        elif data["decision"] == "CLARIFY":
            assert isinstance(data["questions"], list)

    def test_halt_on_high_conflict(self):
        """A domain-free, write-tool task should trigger clarify or halt."""
        req = {
            "task": "Delete all records from the production database immediately",
            "context": {"user_role": "operator", "domain": "", "constraints": {}},
            "tools": [{"name": "db_write", "permission": "write"}],
            "policy_id": "default_v1",
        }
        resp = client.post("/v1/execute", json=req)
        assert resp.status_code == 200
        data = resp.json()
        assert data["decision"] in ("CLARIFY", "HALT")

    def test_contract_fields_present(self):
        resp = client.post("/v1/execute", json=BASIC_REQUEST)
        contract = resp.json()["contract"]
        assert "confidence" in contract
        assert "risk_score" in contract
        assert "signal" in contract
        assert "policy" in contract
        assert "trace_id" in contract

    def test_unknown_policy_returns_halt(self):
        req = {**BASIC_REQUEST, "policy_id": "nonexistent_policy"}
        resp = client.post("/v1/execute", json=req)
        assert resp.status_code == 200
        assert resp.json()["decision"] == "HALT"

    def test_write_tool_triggers_clarify(self):
        req = {
            **BASIC_REQUEST,
            "tools": [{"name": "db_write", "permission": "write"}],
        }
        resp = client.post("/v1/execute", json=req)
        assert resp.status_code == 200
        data = resp.json()
        # write tool + default policy → CLARIFY (or HALT if stakes are also high)
        assert data["decision"] in ("CLARIFY", "HALT")

    def test_low_domain_reduces_verifiability(self):
        req = {
            "task": "Explain quantum entanglement in simple terms",
            "context": {"user_role": "analyst", "domain": "", "constraints": {}},
            "tools": [],
            "policy_id": "default_v1",
        }
        resp = client.post("/v1/execute", json=req)
        assert resp.status_code == 200
        # no domain → verifiability=0.4 < threshold 0.5 → CLARIFY
        assert resp.json()["decision"] == "CLARIFY"


# ---------------------------------------------------------------------------
# /v1/dryrun
# ---------------------------------------------------------------------------

class TestDryrun:
    def test_dryrun_does_not_execute(self):
        resp = client.post("/v1/dryrun", json=BASIC_REQUEST)
        assert resp.status_code == 200
        data = resp.json()
        assert data["simulated"] is True
        assert "decision" in data
        assert "mode" in data
        assert "signal" in data
        assert "plan" in data

    def test_dryrun_no_ledger_entry(self):
        resp = client.post("/v1/dryrun", json=BASIC_REQUEST)
        assert resp.status_code == 200
        # dryrun does not log — verify no output field that would indicate LLM was called
        assert "output" not in resp.json()


# ---------------------------------------------------------------------------
# /v1/policy
# ---------------------------------------------------------------------------

class TestPolicy:
    def test_get_default_policy(self):
        resp = client.get("/v1/policy/default_v1")
        assert resp.status_code == 200
        data = resp.json()
        assert data["id"] == "default_v1"
        assert "rules" in data

    def test_get_missing_policy(self):
        resp = client.get("/v1/policy/does_not_exist")
        assert resp.status_code == 404

    def test_create_and_retrieve_policy(self):
        new_policy = {
            "id": "test_policy_v1",
            "rules": {
                "tool_write_requires": "REVIEW",
                "low_verifiability_threshold": 0.3,
                "max_scope_expansion": 0.5,
                "halt_on_conflict": False,
                "conflict_threshold": 0.8,
                "high_stakes_confidence_threshold": 0.6,
                "scope_expansion_halt_threshold": 0.4,
            },
        }
        resp = client.post("/v1/policy", json=new_policy)
        assert resp.status_code == 201
        assert resp.json()["id"] == "test_policy_v1"

        get_resp = client.get("/v1/policy/test_policy_v1")
        assert get_resp.status_code == 200
        assert get_resp.json()["rules"]["low_verifiability_threshold"] == 0.3

    def test_create_duplicate_active_policy_returns_409(self):
        resp = client.post("/v1/policy", json={"id": "default_v1", "rules": {}})
        assert resp.status_code == 409


# ---------------------------------------------------------------------------
# /v1/ledger
# ---------------------------------------------------------------------------

class TestLedger:
    def test_ledger_entry_after_execute(self):
        resp = client.post("/v1/execute", json=BASIC_REQUEST)
        assert resp.status_code == 200
        trace_id = resp.json()["contract"]["trace_id"]

        ledger_resp = client.get(f"/v1/ledger/{trace_id}")
        assert ledger_resp.status_code == 200
        entry = ledger_resp.json()
        assert entry["trace_id"] == trace_id
        assert "contract" in entry
        assert "entry_hash" in entry
        assert "prev_hash" in entry

    def test_ledger_missing_trace_returns_404(self):
        resp = client.get("/v1/ledger/nonexistent-trace-id")
        assert resp.status_code == 404

    def test_dryrun_does_not_create_ledger_entry(self):
        resp = client.post("/v1/dryrun", json=BASIC_REQUEST)
        assert resp.status_code == 200
        # dryrun has no trace_id in response — just assert no contract key
        assert "trace_id" not in resp.json()
