"""Policy engine — versioned, immutable once active."""
from __future__ import annotations

import threading
from typing import Dict, Optional

from models import Policy, PolicyRules

_lock = threading.Lock()

# In-memory policy store: id -> Policy
_POLICIES: Dict[str, Policy] = {
    "default_v1": Policy(
        id="default_v1",
        rules=PolicyRules(
            tool_write_requires="REVIEW",
            low_verifiability_threshold=0.5,
            max_scope_expansion=0.2,
            halt_on_conflict=True,
            conflict_threshold=0.6,
            high_stakes_confidence_threshold=0.7,
            scope_expansion_halt_threshold=0.3,
        ),
    )
}


def get_policy(policy_id: str) -> Optional[Policy]:
    with _lock:
        return _POLICIES.get(policy_id)


def create_policy(policy: Policy) -> Policy:
    """Store a new policy.  Active policies are immutable — raises if already exists and active."""
    with _lock:
        existing = _POLICIES.get(policy.id)
        if existing and existing.active:
            raise ValueError(f"Policy '{policy.id}' is already active and immutable.")
        _POLICIES[policy.id] = policy
        return policy


def evaluate_decision(
    signal,
    stakes: str,
    confidence: float,
    tools,
    scope_expansion: float,
    policy: Policy,
) -> tuple[str, str]:
    """
    Apply policy rules and return (state, reason).

    Rules (in priority order):
      1. conflict > conflict_threshold → HALT
      2. scope_expansion > scope_expansion_halt_threshold → HALT
      3. tool with write permission present → CLARIFY (requires REVIEW)
      4. verifiability < low_verifiability_threshold → CLARIFY
      5. stakes == high AND confidence < high_stakes_confidence_threshold → CLARIFY
      6. otherwise → PROCEED
    """
    r = policy.rules

    if r.halt_on_conflict and signal.conflict > r.conflict_threshold:
        return "HALT", f"Conflicting signals detected (conflict={signal.conflict:.2f} > {r.conflict_threshold})"

    if scope_expansion > r.scope_expansion_halt_threshold:
        return "HALT", f"Scope expansion too large ({scope_expansion:.2f} > {r.scope_expansion_halt_threshold})"

    for tool in tools:
        if tool.permission == "write" and r.tool_write_requires == "REVIEW":
            return "CLARIFY", f"Tool '{tool.name}' requires write permission — human review needed"

    if signal.verifiability < r.low_verifiability_threshold:
        return (
            "CLARIFY",
            f"Low signal verifiability ({signal.verifiability:.2f} < {r.low_verifiability_threshold})",
        )

    if stakes == "high" and confidence < r.high_stakes_confidence_threshold:
        return (
            "CLARIFY",
            f"High-stakes task with insufficient confidence ({confidence:.2f} < {r.high_stakes_confidence_threshold})",
        )

    return "PROCEED", "All policy checks passed"
