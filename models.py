"""Data models for CASA-RX middleware."""
from __future__ import annotations

from datetime import datetime, timezone
from typing import Any, Dict, List, Literal, Optional

from pydantic import BaseModel, Field


# ---------------------------------------------------------------------------
# Request / context helpers
# ---------------------------------------------------------------------------

class Constraints(BaseModel):
    format: Literal["markdown", "json", "text"] = "text"
    tone: Literal["professional", "neutral"] = "neutral"
    max_tokens: int = 1200


class ContextModel(BaseModel):
    user_role: Literal["operator", "analyst", "builder"] = "analyst"
    domain: str = ""
    constraints: Constraints = Field(default_factory=Constraints)


class ToolPermission(BaseModel):
    name: str
    permission: Literal["read", "write", "review"]


class ExecuteRequest(BaseModel):
    task: str
    context: ContextModel = Field(default_factory=ContextModel)
    tools: List[ToolPermission] = Field(default_factory=list)
    policy_id: str = "default_v1"


# ---------------------------------------------------------------------------
# Core domain models
# ---------------------------------------------------------------------------

class TaskContract(BaseModel):
    objective: str
    constraints: Dict[str, Any] = Field(default_factory=dict)
    success_criteria: List[str] = Field(default_factory=list)
    ambiguities: List[str] = Field(default_factory=list)
    stakes: Literal["low", "medium", "high"] = "medium"


class SignalObject(BaseModel):
    relevance: float = 0.0
    verifiability: float = 0.0
    completeness: float = 0.0
    conflict: float = 0.0
    volatility: float = 0.0


class TaskStep(BaseModel):
    id: int
    desc: str
    deps: List[int] = Field(default_factory=list)


class TaskGraph(BaseModel):
    steps: List[TaskStep] = Field(default_factory=list)
    missing_inputs: List[str] = Field(default_factory=list)


class Decision(BaseModel):
    state: Literal["PROCEED", "CLARIFY", "HALT"]
    reason: str
    risk_score: float = 0.0


class ContractObject(BaseModel):
    trace_id: str
    decision: Literal["PROCEED", "CLARIFY", "HALT"]
    confidence: float
    risk_score: float
    policy_id: str
    signal: SignalObject
    task_hash: str
    timestamp: str


# ---------------------------------------------------------------------------
# Policy models
# ---------------------------------------------------------------------------

class PolicyRules(BaseModel):
    tool_write_requires: Literal["REVIEW", "PROCEED"] = "REVIEW"
    low_verifiability_threshold: float = 0.5
    max_scope_expansion: float = 0.2
    halt_on_conflict: bool = True
    conflict_threshold: float = 0.6
    high_stakes_confidence_threshold: float = 0.7
    scope_expansion_halt_threshold: float = 0.3


class Policy(BaseModel):
    id: str
    rules: PolicyRules = Field(default_factory=PolicyRules)
    created_at: str = Field(default_factory=lambda: datetime.now(timezone.utc).isoformat())
    active: bool = True


# ---------------------------------------------------------------------------
# API response models
# ---------------------------------------------------------------------------

class SignalSummary(BaseModel):
    relevance: float
    verifiability: float
    conflict: float


class ContractSummary(BaseModel):
    confidence: float
    risk_score: float
    signal: SignalSummary
    policy: str
    trace_id: str


class ExecuteResponse(BaseModel):
    decision: Literal["PROCEED", "CLARIFY", "HALT"]
    mode: Literal["answer", "ask", "tool_use", "refuse"]
    output: Optional[str] = None
    questions: List[str] = Field(default_factory=list)
    contract: ContractSummary


# ---------------------------------------------------------------------------
# Ledger
# ---------------------------------------------------------------------------

class LedgerEntry(BaseModel):
    seq: int
    trace_id: str
    prev_hash: str
    entry_hash: str
    timestamp: str
    contract: ContractObject
    request_summary: Dict[str, Any] = Field(default_factory=dict)
