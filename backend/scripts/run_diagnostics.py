"""Controlled diagnostic experiments (correctness-first).

Reproduces corrected rolling baselines under three frozen execution modes
without refetching data. Writes an experiment manifest JSON.
"""

from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path

from app.db.session import SessionLocal
from app.services.research import run_rolling_eval


def main() -> None:
    """Run oc_zero_cost, oc_with_costs, stop_tp_costs long-only diagnostics."""
    modes = ["oc_zero_cost", "oc_with_costs", "stop_tp_costs"]
    stamp_scenarios = ["stress_1pct", "sdrt_0_5pct"]
    results: dict = {
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "protocol": {
            "train_sessions": 85,
            "test_sessions": 5,
            "step_sessions": 5,
            "long_only": True,
            "purge_label_overlap": True,
            "min_prob": 0.55,
            "max_folds": 40,
            "note": (
                "max_folds=40 reserved for quick diagnostics; "
                "full history remains available via API without max_folds. "
                "Prior unrestricted rolling runs are research history, "
                "not fresh holdout for revised designs."
            ),
        },
        "runs": [],
    }
    db = SessionLocal()
    try:
        for mode in modes:
            for stamp in stamp_scenarios:
                if mode == "oc_zero_cost" and stamp != "stress_1pct":
                    continue  # zero-cost ignores stamp
                print(f"Running {mode} / {stamp} …")
                out = run_rolling_eval(
                    db,
                    train_sessions=85,
                    test_sessions=5,
                    step_sessions=5,
                    max_folds=40,
                    min_prob=0.55,
                    long_only=True,
                    execution_mode=mode,
                    stamp_scenario=stamp,
                    purge_label_overlap=True,
                )
                results["runs"].append(
                    {
                        "execution_mode": mode,
                        "stamp_scenario": stamp,
                        "protocol": out.get("protocol"),
                        "models": out.get("models"),
                        "direction_success": out.get("direction_success"),
                        "trading": {
                            k: v
                            for k, v in (out.get("trading") or {}).items()
                            if k != "equity_curve"
                        }
                        | {
                            "equity_curve": (out.get("trading") or {}).get(
                                "equity_curve"
                            )
                        },
                        "experiment_id": out.get("experiment_id"),
                    }
                )
    finally:
        db.close()

    out_dir = Path("sample_artifacts")
    out_dir.mkdir(parents=True, exist_ok=True)
    path = out_dir / "DIAGNOSTIC_MANIFEST.json"
    path.write_text(json.dumps(results, indent=2, default=str))
    print(f"Wrote {path}")
    # Brief stdout summary
    for run in results["runs"]:
        tr = run["trading"]
        eq = tr.get("equity_curve") or {}
        print(
            f"{run['execution_mode']:16} {run['stamp_scenario']:12} "
            f"trades={tr.get('n_trades')} "
            f"win={tr.get('win_rate')} "
            f"avg_net={tr.get('avg_net_return')} "
            f"equity_ret={eq.get('compounded_return')} "
            f"dir_pass={run['direction_success'].get('passed')} "
            f"trade_pass={tr.get('passed')}"
        )


if __name__ == "__main__":
    main()
