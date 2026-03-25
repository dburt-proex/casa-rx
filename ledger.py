"""Append-only, hash-chained audit ledger."""
from __future__ import annotations

import hashlib
import json
import threading
from datetime import datetime, timezone
from typing import Dict, List, Optional

from models import ContractObject, LedgerEntry

_lock = threading.Lock()
_entries: List[LedgerEntry] = []
_index: Dict[str, LedgerEntry] = {}

_GENESIS_HASH = "0" * 64


def _hash_entry(entry: LedgerEntry) -> str:
    payload = json.dumps(
        {
            "seq": entry.seq,
            "trace_id": entry.trace_id,
            "prev_hash": entry.prev_hash,
            "timestamp": entry.timestamp,
            "contract": entry.contract.model_dump(),
        },
        sort_keys=True,
    )
    return hashlib.sha256(payload.encode()).hexdigest()


def append(contract: ContractObject, request_summary: dict | None = None) -> LedgerEntry:
    with _lock:
        seq = len(_entries)
        prev_hash = _entries[-1].entry_hash if _entries else _GENESIS_HASH
        entry = LedgerEntry(
            seq=seq,
            trace_id=contract.trace_id,
            prev_hash=prev_hash,
            entry_hash="",  # placeholder
            timestamp=datetime.now(timezone.utc).isoformat(),
            contract=contract,
            request_summary=request_summary or {},
        )
        entry.entry_hash = _hash_entry(entry)
        _entries.append(entry)
        _index[contract.trace_id] = entry
        return entry


def get(trace_id: str) -> Optional[LedgerEntry]:
    with _lock:
        return _index.get(trace_id)


def all_entries() -> List[LedgerEntry]:
    with _lock:
        return list(_entries)
