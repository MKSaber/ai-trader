import { useEffect, useState } from "react";
import { apiGet, apiPost } from "../api/client";

type Model = {
  id: number;
  version: string;
  model_type: string;
  status: string;
  formula: Record<string, unknown> | null;
  feature_importance: Record<string, number> | null;
  metrics: Record<string, unknown> | null;
  horizon: string;
};

type Tip = {
  symbol?: string | number;
  instrument_id?: number;
  as_of?: string;
  action: string;
  probability_up?: number;
  entry_ref?: number;
  stop_loss?: number;
  take_profit?: number;
  risk_reward?: number | null;
  reason?: string;
  note?: string;
  model?: string;
};

type RollingResult = {
  status: string;
  protocol?: {
    train_sessions: number;
    test_sessions: number;
    step_sessions: number;
    folds: number;
    period_start?: string;
    period_end?: string;
  };
  models?: Array<{
    model_type: string;
    mean_accuracy: number;
    std_accuracy: number;
    folds: number;
  }>;
  direction_success?: {
    passed: boolean;
    best_model?: string;
    best_accuracy?: number;
    naive_accuracy?: number;
    reason?: string;
    criterion?: string;
  };
  trading?: {
    passed: boolean;
    n_trades: number;
    win_rate: number | null;
    sum_net_return: number;
    avg_net_return: number | null;
    exit_reasons?: Record<string, number>;
    criterion?: string;
  };
  recommendations?: Tip[];
  note?: string;
  fetch?: Record<string, unknown> | null;
};

export function ModelsPage() {
  const [rows, setRows] = useState<Model[]>([]);
  const [openId, setOpenId] = useState<number | null>(null);
  const [busy, setBusy] = useState<string | null>(null);
  const [rolling, setRolling] = useState<RollingResult | null>(null);

  const load = () => apiGet<Model[]>("/models").then(setRows);
  useEffect(() => {
    load();
  }, []);

  return (
    <div>
      <header className="page-head">
        <h1>Models</h1>
        <p>
          Rolling walk-forward trains on 85 sessions, tests 5, then slides
          forward — with stop-loss / take-profit paper scoring toward trader
          recommendations.
        </p>
      </header>

      <div className="actions left">
        <button
          disabled={!!busy}
          onClick={async () => {
            setBusy("rolling");
            setRolling(null);
            try {
              const res = await apiPost<RollingResult>(
                "/research/rolling?train_sessions=85&test_sessions=5&step_sessions=5&fetch=false&long_only=true&execution_mode=stop_tp_costs&stamp_scenario=stress_1pct",
              );
              setRolling(res);
              await load();
            } catch (e) {
              setRolling({
                status: "error",
                note: String(e),
              });
            } finally {
              setBusy(null);
            }
          }}
        >
          {busy === "rolling"
            ? "Rolling 85→5 (5y)…"
            : "Rolling walk-forward (5y)"}
        </button>
        <button
          className="secondary"
          disabled={!!busy}
          onClick={async () => {
            setBusy("holdout");
            try {
              const res = await apiPost<RollingResult>(
                "/research/holdout?train_sessions=85&test_sessions=5&fetch=true&lookback_days=1825",
              );
              setRolling({
                status: res.status,
                note: JSON.stringify(res, null, 2),
                direction_success: (res as { success?: RollingResult["direction_success"] })
                  .success,
              });
              await load();
            } catch (e) {
              setRolling({ status: "error", note: String(e) });
            } finally {
              setBusy(null);
            }
          }}
        >
          {busy === "holdout" ? "Holdout…" : "Single 85 / 5 holdout"}
        </button>
        <button
          className="secondary"
          disabled={!!busy}
          onClick={async () => {
            setBusy("train");
            try {
              await apiPost("/research/train");
              await load();
            } finally {
              setBusy(null);
            }
          }}
        >
          Train walk-forward
        </button>
      </div>

      {rolling && (
        <div className="card" style={{ marginBottom: "1.25rem" }}>
          <h3>
            Rolling result{" "}
            <span
              className={`pill ${
                rolling.trading?.passed
                  ? "green"
                  : rolling.direction_success?.passed
                    ? "amber"
                    : "amber"
              }`}
            >
              {rolling.trading?.passed
                ? "trader gate passed"
                : rolling.direction_success?.passed
                  ? "direction only"
                  : "did not pass"}
            </span>
          </h3>
          {rolling.protocol && (
            <p style={{ color: "var(--secondary)" }}>
              {rolling.protocol.folds} folds · train{" "}
              {rolling.protocol.train_sessions} / test{" "}
              {rolling.protocol.test_sessions} · step{" "}
              {rolling.protocol.step_sessions} ·{" "}
              {rolling.protocol.period_start} → {rolling.protocol.period_end}
            </p>
          )}
          {rolling.models && (
            <div className="table-wrap">
              <table>
                <thead>
                  <tr>
                    <th>Model</th>
                    <th>Mean acc</th>
                    <th>Std</th>
                    <th>Folds</th>
                  </tr>
                </thead>
                <tbody>
                  {rolling.models.map((m) => (
                    <tr key={m.model_type}>
                      <td>{m.model_type}</td>
                      <td>{(m.mean_accuracy * 100).toFixed(1)}%</td>
                      <td>{(m.std_accuracy * 100).toFixed(1)}%</td>
                      <td>{m.folds}</td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          )}
          {rolling.trading && (
            <p style={{ marginTop: "0.75rem" }}>
              Trades {rolling.trading.n_trades} · win rate{" "}
              {rolling.trading.win_rate != null
                ? `${(rolling.trading.win_rate * 100).toFixed(1)}%`
                : "—"}{" "}
              · sum net{" "}
              {(rolling.trading.sum_net_return * 100).toFixed(2)}% ·{" "}
              {rolling.trading.criterion}
            </p>
          )}
          {rolling.recommendations && rolling.recommendations.length > 0 && (
            <>
              <h3 style={{ marginTop: "1rem" }}>Recommendations</h3>
              <div className="table-wrap">
                <table>
                  <thead>
                    <tr>
                      <th>Symbol</th>
                      <th>Action</th>
                      <th>P(up)</th>
                      <th>Entry</th>
                      <th>Stop</th>
                      <th>Take profit</th>
                      <th>R:R</th>
                    </tr>
                  </thead>
                  <tbody>
                    {rolling.recommendations.map((t, i) => (
                      <tr key={`${t.symbol}-${i}`}>
                        <td>{String(t.symbol ?? t.instrument_id)}</td>
                        <td>
                          <span
                            className={`pill ${
                              t.action === "buy"
                                ? "green"
                                : t.action === "sell_short"
                                  ? "red"
                                  : ""
                            }`}
                          >
                            {t.action}
                          </span>
                        </td>
                        <td>
                          {t.probability_up != null
                            ? `${(t.probability_up * 100).toFixed(1)}%`
                            : "—"}
                        </td>
                        <td>
                          {t.entry_ref != null ? t.entry_ref.toFixed(2) : "—"}
                        </td>
                        <td>
                          {t.stop_loss != null ? t.stop_loss.toFixed(2) : "—"}
                        </td>
                        <td>
                          {t.take_profit != null
                            ? t.take_profit.toFixed(2)
                            : "—"}
                        </td>
                        <td>
                          {t.risk_reward != null
                            ? t.risk_reward.toFixed(2)
                            : "—"}
                        </td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              </div>
            </>
          )}
          {rolling.note && rolling.status === "error" && (
            <pre className="mono">{rolling.note}</pre>
          )}
        </div>
      )}

      <div className="grid" style={{ gap: "0.85rem" }}>
        {rows.length === 0 && (
          <div className="card">
            <p className="empty">No models yet.</p>
          </div>
        )}
        {rows.map((m) => {
          const open = openId === m.id;
          return (
            <div className="card" key={m.id} style={{ cursor: "pointer" }}>
              <div
                onClick={() => setOpenId(open ? null : m.id)}
                style={{
                  display: "flex",
                  justifyContent: "space-between",
                  alignItems: "center",
                  gap: "1rem",
                }}
              >
                <div>
                  <h3 style={{ marginBottom: "0.35rem" }}>
                    {m.model_type}{" "}
                    <span
                      className={`pill ${
                        m.status === "champion" ? "blue" : ""
                      }`}
                    >
                      {m.status}
                    </span>
                  </h3>
                  <div className="mono">{m.version}</div>
                </div>
                <span className="pill">{open ? "Hide" : "Details"}</span>
              </div>

              {open && (
                <div style={{ marginTop: "1rem" }}>
                  <p style={{ marginBottom: "0.5rem" }}>
                    Horizon: {m.horizon}
                  </p>
                  {m.formula && (
                    <pre className="mono">
                      {JSON.stringify(m.formula, null, 2)}
                    </pre>
                  )}
                  {m.feature_importance && (
                    <pre className="mono">
                      {JSON.stringify(m.feature_importance, null, 2)}
                    </pre>
                  )}
                  {m.metrics && (
                    <pre className="mono">
                      {JSON.stringify(m.metrics, null, 2)}
                    </pre>
                  )}
                  {m.status !== "champion" && (
                    <div className="actions left" style={{ marginTop: "1rem" }}>
                      <button
                        onClick={async (e) => {
                          e.stopPropagation();
                          await apiPost("/models/promote", {
                            model_id: m.id,
                            approve: true,
                          });
                          load();
                        }}
                      >
                        Make champion
                      </button>
                      <button
                        className="secondary"
                        onClick={async (e) => {
                          e.stopPropagation();
                          await apiPost("/models/promote", {
                            model_id: m.id,
                            approve: false,
                          });
                          load();
                        }}
                      >
                        Reject
                      </button>
                      {(m.status === "retired" || m.status === "candidate") && (
                        <button
                          className="secondary"
                          onClick={async (e) => {
                            e.stopPropagation();
                            await apiPost("/models/rollback", {
                              model_id: m.id,
                            });
                            load();
                          }}
                        >
                          Rollback to this
                        </button>
                      )}
                    </div>
                  )}
                </div>
              )}
            </div>
          );
        })}
      </div>
    </div>
  );
}
