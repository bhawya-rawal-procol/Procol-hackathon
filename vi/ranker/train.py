"""Train two models on synthetic history and report HONEST out-of-time AUC.

  P(bid)          — does an invited vendor submit a bid?             -> used by the participation forecast
  P(bid & top-3)  — does the vendor bid AND land in the top 3 by price? -> the ranking score

Split is by time (first 70% of events train, last 30% test) so the test AUC is a fair estimate.
Models are then refit on all rows and pickled to data/models/. This is THE AI component; everything
around it is deterministic. Run: python -m vi.ranker.train --db data/vendor_intelligence.db
"""
from __future__ import annotations

import argparse
import json
import pickle
from pathlib import Path

import numpy as np
from sklearn.ensemble import GradientBoostingClassifier
from sklearn.linear_model import LogisticRegression
from sklearn.metrics import roc_auc_score
from sklearn.pipeline import make_pipeline
from sklearn.preprocessing import StandardScaler

from ..db import DEFAULT_DB, connect, rows
from .features import FEATURE_NAMES, event_features, vendor_vector

MODEL_DIR = Path("data/models")

LABEL_SQL = """
WITH latest AS (
  SELECT b.trade_request_id AS tr_id, b.vendor_company_id AS v, b.id AS bid_id
  FROM bids b
  WHERE b.created_at = (SELECT MAX(b2.created_at) FROM bids b2
                        WHERE b2.trade_request_id = b.trade_request_id AND b2.vendor_company_id = b.vendor_company_id)
),
tot AS (SELECT l.tr_id, l.v, SUM(btp.price * btp.quantity) AS total
        FROM latest l JOIN bid_trade_products btp ON btp.bid_id = l.bid_id GROUP BY 1, 2),
ranked AS (SELECT tr_id, v, RANK() OVER (PARTITION BY tr_id ORDER BY total) AS rnk FROM tot)
SELECT a.trade_request_id AS tr_id, a.vendor_company_id AS v, eg.company_id AS buyer, tr.bid_start_time,
       (r.rnk IS NOT NULL) AS bid, (r.rnk IS NOT NULL AND r.rnk <= 3) AS top3
FROM audiences a
JOIN trade_requests tr ON tr.id = a.trade_request_id AND tr.status = 'closed'
JOIN event_groups eg ON eg.id = tr.event_group_id
LEFT JOIN ranked r ON r.tr_id = a.trade_request_id AND r.v = a.vendor_company_id
ORDER BY tr.bid_start_time, a.trade_request_id, a.vendor_company_id
"""


def build_dataset(conn):
    X, y_bid, y_top3, times = [], [], [], []
    ev_cache: dict[int, dict] = {}
    for r in rows(conn, LABEL_SQL):
        ev = ev_cache.get(r["tr_id"]) or ev_cache.setdefault(r["tr_id"], event_features(conn, r["tr_id"]))
        x, _ = vendor_vector(conn, r["buyer"], r["v"], ev, as_of=r["bid_start_time"])
        X.append(x); y_bid.append(int(r["bid"])); y_top3.append(int(r["top3"])); times.append(r["bid_start_time"])
    return np.array(X), np.array(y_bid), np.array(y_top3), times


def _candidates():
    return {
        "gbm": lambda: GradientBoostingClassifier(n_estimators=150, max_depth=2, learning_rate=0.05, subsample=0.9, random_state=7),
        "logreg": lambda: make_pipeline(StandardScaler(), LogisticRegression(max_iter=2000, C=0.5)),
    }


def fit_and_report(X, y, times, label: str) -> tuple[object, dict]:
    cut = int(len(y) * 0.7)
    report = {"label": label, "rows": int(len(y)), "positives": int(y.sum()),
              "train_rows": cut, "test_rows": int(len(y) - cut),
              "split_time": times[cut], "test_auc": {}}
    best_name, best_auc, best_factory = None, -1.0, None
    for name, factory in _candidates().items():
        m = factory().fit(X[:cut], y[:cut])
        auc = roc_auc_score(y[cut:], m.predict_proba(X[cut:])[:, 1]) if len(set(y[cut:])) > 1 else float("nan")
        report["test_auc"][name] = round(float(auc), 3)
        if auc > best_auc:
            best_name, best_auc, best_factory = name, auc, factory
    report["chosen"] = best_name
    final = best_factory().fit(X, y)          # refit on everything for serving
    return final, report


def train(db_path: str) -> dict:
    conn = connect(db_path)
    X, y_bid, y_top3, times = build_dataset(conn)
    MODEL_DIR.mkdir(parents=True, exist_ok=True)
    out = {"features": FEATURE_NAMES, "models": {}}
    for label, y in (("p_bid", y_bid), ("p_top3", y_top3)):
        model, rep = fit_and_report(X, y, times, label)
        with open(MODEL_DIR / f"{label}.pkl", "wb") as f:
            pickle.dump(model, f)
        out["models"][label] = rep
    out["feature_means"] = [float(v) for v in X.mean(axis=0)]
    (MODEL_DIR / "metrics.json").write_text(json.dumps(out, indent=2))
    return out


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--db", default=DEFAULT_DB)
    args = ap.parse_args()
    res = train(args.db)
    for label, rep in res["models"].items():
        print(f"{label:<7} rows={rep['rows']} positives={rep['positives']} test_auc={rep['test_auc']} -> {rep['chosen']}")
    print(f"models written to {MODEL_DIR}/")
