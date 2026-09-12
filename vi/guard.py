"""ConfidentialityGuard — every vendor-facing payload passes through here. No exceptions.

Rules (see README §"The one rule"):
  1. A vendor never sees a competitor's absolute price, name, or rank.   -> key deny-list + name scan
  2. Aggregates over other vendors require k >= 3 contributors.          -> k-anonymity
  3. The buyer's vendor_feedback_policy decides how much the vendor sees:
       none                     -> nothing at all
       relative_only            -> relative/own data, technical section removed
       relative_plus_technical  -> relative/own data + own technical scores (unrestricted only)

The guard is deterministic, pure, and returns an audit of everything it removed and why.
"""
from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import Any

POLICIES = ("none", "relative_only", "relative_plus_technical")
K_ANON = 3

# Keys that carry another party's absolute data. Matched on the last path segment, case-insensitive.
FORBIDDEN_KEYS = {
    "l1_price", "l1_total", "l1_amount", "l1_vendor", "l1_vendor_id", "l1_vendor_name",
    "winner", "winner_id", "winner_name", "winner_price", "winner_total",
    "competitor", "competitors", "competitor_price", "competitor_prices", "competitor_name",
    "other_bids", "bids_by_vendor", "vendor_prices", "all_bids", "rankings", "leaderboard",
    "rank_of_others", "vendor_ranking", "selected_vendor", "selected_vendor_id",
}
# Anything whose key matches these is also stripped (covers e.g. "top_vendor_names", "l1_bidder_total").
FORBIDDEN_KEY_RE = re.compile(r"(^|_)(l1_(vendor|bidder|price|total|amount|name)|competitor|winner|other_vendor)(s?)(_|$)", re.I)
# Explicitly allowed relative fields that would otherwise trip the regex.
ALLOWED_KEYS = {"gap_to_l1_pct", "avg_gap_to_l1_pct", "own_gap_to_l1_pct", "hist_gap_to_l1_pct",
                "rank_position", "n_bidders", "rank_of_n", "you_were"}
# Aggregate fields that must carry a sibling "k" (or "<name>_k") >= K_ANON.
AGGREGATE_SUFFIXES = ("_median", "_peer_median", "_peer_avg", "_category_median", "_p25", "_p75")
TECHNICAL_KEYS_RE = re.compile(r"technical|evaluation|section", re.I)


@dataclass
class GuardResult:
    payload: Any
    audit: list[dict] = field(default_factory=list)
    policy: str = "relative_only"

    @property
    def stripped_count(self) -> int:
        return len(self.audit)


class ConfidentialityGuard:
    def __init__(self, own_vendor_id: int, own_vendor_name: str, buyer_name: str,
                 other_vendor_names: list[str]):
        self.own_vendor_id = own_vendor_id
        self.safe_names = {own_vendor_name.lower(), buyer_name.lower()}
        # names of every OTHER vendor: any appearance in a string value is stripped
        self.other_names = [n for n in other_vendor_names if n.lower() not in self.safe_names]
        self._name_re = re.compile("|".join(re.escape(n) for n in self.other_names), re.I) if self.other_names else None

    # ------------------------------------------------------------------ public
    def apply(self, payload: Any, policy: str) -> GuardResult:
        if policy not in POLICIES:
            raise ValueError(f"unknown vendor_feedback_policy {policy!r}")
        res = GuardResult(payload=None, policy=policy)
        if policy == "none":
            res.audit.append({"path": "$", "action": "blank_all", "reason": "policy=none"})
            res.payload = {}
            return res
        res.payload = self._walk(payload, "$", policy, res.audit)
        return res

    # ------------------------------------------------------------------ walk
    def _walk(self, node: Any, path: str, policy: str, audit: list[dict]) -> Any:
        if isinstance(node, dict):
            out: dict[str, Any] = {}
            for k, v in node.items():
                p = f"{path}.{k}"
                key = str(k)
                if self._forbidden_key(key):
                    audit.append({"path": p, "action": "strip", "reason": "competitor_absolute_data_key"})
                    continue
                if policy == "relative_only" and TECHNICAL_KEYS_RE.search(key):
                    audit.append({"path": p, "action": "strip", "reason": "policy=relative_only removes technical"})
                    continue
                if key.endswith(AGGREGATE_SUFFIXES) and not self._k_ok(node, key):
                    audit.append({"path": p, "action": "strip", "reason": f"k-anonymity: fewer than {K_ANON} contributors"})
                    continue
                out[k] = self._walk(v, p, policy, audit)
            return out
        if isinstance(node, list):
            return [self._walk(v, f"{path}[{i}]", policy, audit) for i, v in enumerate(node)]
        if isinstance(node, str) and self._name_re and self._name_re.search(node):
            audit.append({"path": path, "action": "redact", "reason": "competitor_name_in_text"})
            return self._name_re.sub("[another vendor]", node)
        return node

    def _forbidden_key(self, key: str) -> bool:
        k = key.lower()
        if k in ALLOWED_KEYS:
            return False
        return k in FORBIDDEN_KEYS or bool(FORBIDDEN_KEY_RE.search(k))

    @staticmethod
    def _k_ok(parent: dict, key: str) -> bool:
        base = key
        for suf in AGGREGATE_SUFFIXES:
            if key.endswith(suf):
                base = key[: -len(suf)]
                break
        k = parent.get(f"{base}_k", parent.get("k"))
        return isinstance(k, (int, float)) and k >= K_ANON


def strip_restricted_technical(sections: list[dict]) -> tuple[list[dict], list[dict]]:
    """Restricted evaluation scores are never shown to the vendor, regardless of policy."""
    kept, audit = [], []
    for s in sections:
        if s.get("score_type") == "restricted":
            audit.append({"path": f"$.technical.sections[{s.get('section_key')}]", "action": "strip",
                          "reason": "evaluation score_type=restricted"})
        else:
            kept.append(s)
    return kept, audit
