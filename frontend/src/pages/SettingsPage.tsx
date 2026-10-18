import { useEffect, useState } from "react";
import { apiGet } from "../api/client";

type Settings = {
  default_horizon: string;
  intraday_interval_minutes: number;
  commission_bps: number;
  spread_bps: number;
  slippage_bps: number;
  stamp_duty_rate: number;
  market_data_provider: string;
  demo_mode: boolean;
  benchmark: string;
};

export function SettingsPage() {
  const [s, setS] = useState<Settings | null>(null);

  useEffect(() => {
    apiGet<Settings>("/settings").then(setS);
  }, []);

  const rows: [string, string | number | boolean | undefined][] = s
    ? [
        ["Forecast horizon", s.default_horizon],
        ["Intraday interval (min)", s.intraday_interval_minutes],
        ["Commission (bps)", s.commission_bps],
        ["Spread (bps)", s.spread_bps],
        ["Slippage (bps)", s.slippage_bps],
        ["UK stamp duty", `${(s.stamp_duty_rate * 100).toFixed(2)}%`],
        ["Market data provider", s.market_data_provider],
        ["Demo mode", s.demo_mode ? "on" : "off"],
        ["Benchmark", s.benchmark],
      ]
    : [];

  return (
    <div>
      <header className="page-head">
        <h1>Settings</h1>
        <p>
          Visible assumptions. Change them via environment variables — the UI
          does not invent hidden costs.
        </p>
      </header>

      <div className="card">
        {!s ? (
          <p className="empty">Loading…</p>
        ) : (
          <div className="table-wrap">
            <table>
              <tbody>
                {rows.map(([k, v]) => (
                  <tr key={k}>
                    <td style={{ color: "var(--secondary)" }}>{k}</td>
                    <td>
                      <strong>{String(v)}</strong>
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
