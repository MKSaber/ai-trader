import { useEffect, useState } from "react";
import { apiGet } from "../api/client";

type Backtest = {
  status: string;
  message?: string;
  n?: number;
  costs?: Record<string, number>;
  round_trip_cost_fraction?: number;
  gross_mean?: number;
  net_mean?: number;
  net_total_compounded?: number;
  volatility?: number | null;
  max_drawdown?: number | null;
  hit_rate_when_long?: number;
  benchmark?: string;
  note?: string;
};

export function BacktestsPage() {
  const [data, setData] = useState<Backtest | null>(null);

  useEffect(() => {
    apiGet<Backtest>("/backtests").then(setData);
  }, []);

  return (
    <div>
      <header className="page-head">
        <h1>Backtests</h1>
        <p>
          Cost-aware portfolio view of resolved forecasts — separate from raw
          prediction metrics. No promised outperformance.
        </p>
      </header>

      {!data ? (
        <div className="card">
          <p className="empty">Loading…</p>
        </div>
      ) : data.status !== "ok" ? (
        <div className="banner">{data.message}</div>
      ) : (
        <>
          <div className="grid grid-3">
            <div className="card stat">
              <div className="value">{data.n}</div>
              <div className="label">Resolved forecasts</div>
            </div>
            <div className="card stat">
              <div className="value">
                {((data.net_mean ?? 0) * 100).toFixed(2)}%
              </div>
              <div className="label">Mean net return</div>
            </div>
            <div className="card stat">
              <div className="value">
                {((data.max_drawdown ?? 0) * 100).toFixed(1)}%
              </div>
              <div className="label">Max drawdown</div>
            </div>
          </div>
          <div className="card" style={{ marginTop: "1.1rem" }}>
            <h3>Assumptions</h3>
            <pre className="mono">{JSON.stringify(data.costs, null, 2)}</pre>
            <p style={{ marginTop: "0.75rem" }}>{data.benchmark}</p>
            <p style={{ marginTop: "0.35rem" }}>{data.note}</p>
          </div>
        </>
      )}
    </div>
  );
}
