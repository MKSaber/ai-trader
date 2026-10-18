import { useEffect, useState } from "react";
import { apiGet, apiPost } from "../api/client";

type Pred = {
  id: number;
  symbol: string | number;
  issued_at: string;
  horizon: string;
  expected_return: number | null;
  probability_up: number | null;
  model_version: string | null;
  realised_return: number | null;
  outcome_correct: boolean | null;
};

export function ForecastsPage() {
  const [rows, setRows] = useState<Pred[]>([]);
  const [busy, setBusy] = useState(false);

  const load = () => apiGet<Pred[]>("/predictions").then(setRows);
  useEffect(() => {
    load();
  }, []);

  return (
    <div>
      <header className="page-head">
        <h1>Forecasts</h1>
        <p>
          Issued once, then frozen. Outcomes append later — we never rewrite
          history.
        </p>
      </header>

      <div className="actions left">
        <button
          disabled={busy}
          onClick={async () => {
            setBusy(true);
            await apiPost("/research/predict");
            await load();
            setBusy(false);
          }}
        >
          Issue from champion
        </button>
        <button
          className="secondary"
          disabled={busy}
          onClick={async () => {
            setBusy(true);
            await apiPost("/research/resolve");
            await load();
            setBusy(false);
          }}
        >
          Resolve matured
        </button>
      </div>

      <div className="card">
        {rows.length === 0 ? (
          <p className="empty">No forecasts yet. Train a model first.</p>
        ) : (
          <div className="table-wrap">
            <table>
              <thead>
                <tr>
                  <th>Symbol</th>
                  <th>Issued</th>
                  <th>E[return]</th>
                  <th>P(up)</th>
                  <th>Model</th>
                  <th>Result</th>
                </tr>
              </thead>
              <tbody>
                {rows.map((r) => (
                  <tr key={r.id}>
                    <td>
                      <strong>{r.symbol}</strong>
                    </td>
                    <td className="mono">{r.issued_at.slice(0, 19)}</td>
                    <td>{r.expected_return?.toFixed?.(4) ?? "—"}</td>
                    <td>{r.probability_up?.toFixed?.(3) ?? "—"}</td>
                    <td className="mono">{r.model_version}</td>
                    <td>
                      {r.realised_return == null ? (
                        <span className="pill">pending</span>
                      ) : (
                        <span
                          className={`pill ${r.outcome_correct ? "green" : "red"}`}
                        >
                          {r.outcome_correct ? "direction ok" : "miss"}
                        </span>
                      )}
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        )}
      </div>
    </div>
  );
}
