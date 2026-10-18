import { useEffect, useState } from "react";
import { apiGet } from "../api/client";

type SetupResp = {
  disabled: boolean;
  reason?: string;
  setups: Array<{
    id: number;
    signal_ts: string;
    model_version: string;
    entry_low: number | null;
    entry_high: number | null;
    stop_loss: number | null;
    take_profit: number | null;
    expected_net_return: number | null;
    reason: string;
    no_trade: boolean;
    outcome: string | null;
    ambiguity_flag: boolean;
  }>;
};

type LedgerRow = {
  as_of: string;
  cash_gbp: number;
  equity_gbp: number;
};

export function IntradayLabPage() {
  const [data, setData] = useState<SetupResp | null>(null);
  const [ledger, setLedger] = useState<LedgerRow[]>([]);

  useEffect(() => {
    apiGet<SetupResp>("/intraday/setups").then(setData);
    apiGet<LedgerRow[]>("/intraday/ledger").then(setLedger);
  }, []);

  const latest = ledger[0];

  return (
    <div>
      <header className="page-head">
        <h1>Intraday</h1>
        <p>
          Paper setups only. Long entries, then sell to close. Touching a limit
          does not guarantee a fill.
        </p>
      </header>

      {data?.disabled && (
        <div className="banner danger">{data.reason}</div>
      )}

      <div className="grid grid-3" style={{ marginBottom: "1.1rem" }}>
        <div className="card stat">
          <div className="value">
            {latest ? `£${latest.equity_gbp.toFixed(0)}` : "—"}
          </div>
          <div className="label">Paper equity</div>
        </div>
        <div className="card stat">
          <div className="value">{data?.setups?.length ?? 0}</div>
          <div className="label">Setups stored</div>
        </div>
        <div className="card stat">
          <div className="value">
            {data?.setups?.filter((s) => s.ambiguity_flag).length ?? 0}
          </div>
          <div className="label">Ambiguous bars</div>
        </div>
      </div>

      <div className="card">
        <h3>Setups</h3>
        {!data?.setups?.length ? (
          <p className="empty">
            {data?.disabled
              ? "Waiting for intraday bars."
              : "No setups yet — run the pipeline after loading 5-minute data."}
          </p>
        ) : (
          <div className="table-wrap">
            <table>
              <thead>
                <tr>
                  <th>Signal</th>
                  <th>Entry</th>
                  <th>Stop / Target</th>
                  <th>E[net]</th>
                  <th>Outcome</th>
                </tr>
              </thead>
              <tbody>
                {data.setups.map((s) => (
                  <tr key={s.id}>
                    <td className="mono">{s.signal_ts.slice(0, 19)}</td>
                    <td>
                      {s.no_trade ? (
                        <span className="pill amber">No trade</span>
                      ) : (
                        `${s.entry_low?.toFixed(3)} – ${s.entry_high?.toFixed(3)}`
                      )}
                    </td>
                    <td>
                      {s.stop_loss?.toFixed(3)} / {s.take_profit?.toFixed(3)}
                    </td>
                    <td>{s.expected_net_return?.toFixed(4) ?? "—"}</td>
                    <td>
                      {s.outcome || "—"}{" "}
                      {s.ambiguity_flag && (
                        <span className="pill red">ambiguous</span>
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
