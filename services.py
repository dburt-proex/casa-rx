"""Core CASA-RX services."""
from __future__ import annotations

import hashlib
import uuid
from datetime import datetime, timezone
from typing import List

from models import (
    ContractObject,
    Decision,
    ExecuteRequest,
    SignalObject,
    TaskContract,
    TaskGraph,
    TaskStep,
    ToolPermission,
)
from policy_engine import evaluate_decision, get_policy


# ---------------------------------------------------------------------------
# Intent Lock Service
# ---------------------------------------------------------------------------

def intent_lock(req: ExecuteRequest) -> TaskContract:
    """Parse task into a TaskContract, detect ambiguities."""
    task = req.task.strip()
    ambiguities: List[str] = []
    constraints = req.context.constraints.model_dump()

    if len(task.split()) < 3:
        ambiguities.append("Task description is too brief — please provide more context.")

    if not req.context.domain:
        ambiguities.append("Domain is unspecified.")

    stakes = _estimate_stakes(task, req.tools)

    return TaskContract(
        objective=task,
        constraints=constraints,
        success_criteria=[f"Produce a valid {constraints.get('format', 'text')} response"],
        ambiguities=ambiguities,
        stakes=stakes,
    )


def _estimate_stakes(task: str, tools: List[ToolPermission]) -> str:
    task_lower = task.lower()
    high_keywords = {"delete", "remove", "drop", "wipe", "erase", "publish", "deploy", "production"}
    medium_keywords = {"update", "modify", "change", "write", "create", "insert"}

    for tool in tools:
        if tool.permission == "write":
            return "high"

    if any(kw in task_lower for kw in high_keywords):
        return "high"
    if any(kw in task_lower for kw in medium_keywords):
        return "medium"
    return "low"


# ---------------------------------------------------------------------------
# Signal Qualification Service
# ---------------------------------------------------------------------------

def score_signal(req: ExecuteRequest) -> SignalObject:
    """Score evidence quality for the request."""
    task_len = len(req.task.split())
    has_domain = bool(req.context.domain)
    has_tools = bool(req.tools)

    # Heuristic scoring — real impl would use NLP / knowledge base
    relevance = min(1.0, task_len / 20)
    verifiability = 0.8 if has_domain else 0.4
    completeness = 0.9 if (has_domain and task_len > 5) else 0.5
    conflict = 0.15 if has_tools else 0.05
    volatility = 0.2 if has_tools else 0.1

    return SignalObject(
        relevance=round(relevance, 3),
        verifiability=round(verifiability, 3),
        completeness=round(completeness, 3),
        conflict=round(conflict, 3),
        volatility=round(volatility, 3),
    )


# ---------------------------------------------------------------------------
# Planning & Control Matrix
# ---------------------------------------------------------------------------

def build_plan(task: TaskContract) -> TaskGraph:
    """Build a simple task graph from the contract."""
    missing: List[str] = list(task.ambiguities)
    steps = [
        TaskStep(id=1, desc="Understand and validate task objective", deps=[]),
        TaskStep(id=2, desc="Gather required information / invoke tools", deps=[1]),
        TaskStep(id=3, desc="Generate response", deps=[2]),
        TaskStep(id=4, desc="Validate output against constraints", deps=[3]),
    ]
    return TaskGraph(steps=steps, missing_inputs=missing)


# ---------------------------------------------------------------------------
# Gate & Risk Engine
# ---------------------------------------------------------------------------

def gate(
    task: TaskContract,
    signal: SignalObject,
    plan: TaskGraph,
    policy_id: str = "default_v1",
    tools: List[ToolPermission] | None = None,
) -> Decision:
    """Classify request → Decision using the policy engine."""
    policy = get_policy(policy_id)
    if policy is None:
        return Decision(state="HALT", reason=f"Unknown policy: {policy_id}", risk_score=1.0)

    scope_expansion = len(plan.missing_inputs) * 0.1
    confidence = compute_confidence(signal)
    risk_score = _compute_risk(signal, task, scope_expansion)

    state, reason = evaluate_decision(
        signal=signal,
        stakes=task.stakes,
        confidence=confidence,
        tools=tools or [],
        scope_expansion=scope_expansion,
        policy=policy,
    )
    return Decision(state=state, reason=reason, risk_score=round(risk_score, 3))


def compute_confidence(signal: SignalObject) -> float:
    return round((signal.relevance + signal.verifiability + signal.completeness) / 3, 3)


def _compute_risk(signal: SignalObject, task: TaskContract, scope_expansion: float) -> float:
    base = 1.0 - compute_confidence(signal)
    conflict_penalty = signal.conflict * 0.3
    stakes_penalty = {"low": 0.0, "medium": 0.1, "high": 0.25}.get(task.stakes, 0.0)
    scope_penalty = scope_expansion * 0.2
    return min(1.0, base + conflict_penalty + stakes_penalty + scope_penalty)


# ---------------------------------------------------------------------------
# Execution Router / LLM stub
# ---------------------------------------------------------------------------

def determine_mode(decision: Decision, task: TaskContract, tools: List[ToolPermission]) -> str:
    if decision.state == "HALT":
        return "refuse"
    if decision.state == "CLARIFY":
        return "ask"
    if tools:
        return "tool_use"
    return "answer"


def call_llm(task: TaskContract, plan: TaskGraph) -> str:
    """Stub LLM call — in production this would proxy to an LLM provider."""
    steps = ", ".join(s.desc for s in plan.steps)
    return (
        f"[CASA-RX stub] Processed task: '{task.objective}'. "
        f"Execution plan: {steps}."
    )


# ---------------------------------------------------------------------------
# Contract Generator
# ---------------------------------------------------------------------------

def build_contract(
    task: TaskContract,
    signal: SignalObject,
    decision: Decision,
    policy_id: str,
) -> ContractObject:
    trace_id = str(uuid.uuid4())
    task_hash = hashlib.sha256(task.objective.encode()).hexdigest()
    confidence = compute_confidence(signal)
    return ContractObject(
        trace_id=trace_id,
        decision=decision.state,
        confidence=round(confidence, 3),
        risk_score=decision.risk_score,
        policy_id=policy_id,
        signal=signal,
        task_hash=task_hash,
        timestamp=datetime.now(timezone.utc).isoformat(),
    )
