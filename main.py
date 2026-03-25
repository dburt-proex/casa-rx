"""CASA-RX — FastAPI application."""
from __future__ import annotations

from typing import Any, Dict, List

from fastapi import FastAPI, HTTPException
from pydantic import BaseModel

import ledger as ledger_module
import policy_engine
import services
from models import (
    ContractSummary,
    ExecuteRequest,
    ExecuteResponse,
    Policy,
    SignalSummary,
)

app = FastAPI(
    title="CASA-RX",
    description="Reasoning Governance Middleware — deterministic gates, contracts, audit trails.",
    version="1.0.0",
)


# ---------------------------------------------------------------------------
# POST /v1/execute
# ---------------------------------------------------------------------------

@app.post("/v1/execute", response_model=ExecuteResponse)
def execute(req: ExecuteRequest) -> ExecuteResponse:
    task = services.intent_lock(req)
    signal = services.score_signal(req)
    plan = services.build_plan(task)
    decision = services.gate(task, signal, plan, req.policy_id, req.tools)

    mode = services.determine_mode(decision, task, req.tools)
    output: str | None = None
    questions: List[str] = []

    if decision.state == "HALT":
        output = None
    elif decision.state == "CLARIFY":
        questions = task.ambiguities or [decision.reason]
    else:
        output = services.call_llm(task, plan)

    contract = services.build_contract(task, signal, decision, req.policy_id)
    ledger_module.append(contract, request_summary={"task": req.task, "policy_id": req.policy_id})

    return ExecuteResponse(
        decision=decision.state,
        mode=mode,
        output=output,
        questions=questions,
        contract=ContractSummary(
            confidence=contract.confidence,
            risk_score=contract.risk_score,
            signal=SignalSummary(
                relevance=signal.relevance,
                verifiability=signal.verifiability,
                conflict=signal.conflict,
            ),
            policy=contract.policy_id,
            trace_id=contract.trace_id,
        ),
    )


# ---------------------------------------------------------------------------
# POST /v1/dryrun
# ---------------------------------------------------------------------------

@app.post("/v1/dryrun")
def dryrun(req: ExecuteRequest) -> Dict[str, Any]:
    """Simulate decision without executing tools or calling LLM."""
    task = services.intent_lock(req)
    signal = services.score_signal(req)
    plan = services.build_plan(task)
    decision = services.gate(task, signal, plan, req.policy_id, req.tools)
    mode = services.determine_mode(decision, task, req.tools)
    confidence = services.compute_confidence(signal)

    return {
        "simulated": True,
        "decision": decision.state,
        "mode": mode,
        "reason": decision.reason,
        "risk_score": decision.risk_score,
        "confidence": round(confidence, 3),
        "signal": signal.model_dump(),
        "plan": plan.model_dump(),
        "missing_inputs": plan.missing_inputs,
    }


# ---------------------------------------------------------------------------
# Policy endpoints
# ---------------------------------------------------------------------------

@app.get("/v1/policy/{policy_id}")
def get_policy(policy_id: str) -> Policy:
    policy = policy_engine.get_policy(policy_id)
    if policy is None:
        raise HTTPException(status_code=404, detail=f"Policy '{policy_id}' not found.")
    return policy


@app.post("/v1/policy", response_model=Policy, status_code=201)
def create_policy(policy: Policy) -> Policy:
    try:
        return policy_engine.create_policy(policy)
    except ValueError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc


# ---------------------------------------------------------------------------
# Ledger endpoints
# ---------------------------------------------------------------------------

@app.get("/v1/ledger/{trace_id}")
def get_ledger_entry(trace_id: str) -> Dict[str, Any]:
    entry = ledger_module.get(trace_id)
    if entry is None:
        raise HTTPException(status_code=404, detail=f"Trace '{trace_id}' not found in ledger.")
    return entry.model_dump()
