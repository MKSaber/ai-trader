import { useEffect, useState } from "react";
import { apiGet } from "../api/client";

type Instrument = {
  id: number;
  symbol: string;
  yahoo_symbol: string | null;
  currency_quoted: string;
  sector: string | null;
};

type Bars = {
  daily: Array<{
    date: string;
    open: number;
    high: number;
    low: number;
    close: number;
    volume: number;
  }>;
};

export function StocksPage() {
  const [list, setList] = useState<Instrument[]>([]);
  const [selected, setSelected] = useState<Instrument | null>(null);
  const [bars, setBars] = useState<Bars | null>(null);

  useEffect(() => {
    apiGet<Instrument[]>("/instruments").then(setList);
  }, []);

  async function select(inst: Instrument) {
    setSelected(inst);
    setBars(await apiGet<Bars>(`/instruments/${inst.id}/bars`));
  }

  const closes = bars?.daily?.map((b) => b.close) ?? [];
  const min = closes.length ? Math.min(...closes) : 0;
  const max = closes.length ? Math.max(...closes) : 1;
  const span = max - min || 1;

  return (
    <div>
      <header className="page-head">
        <h1>Stocks</h1>
        <p>Browse instruments and a simple close series — prices stay in the API.</p>
      </header>

      <div className="grid grid-2">
        <div className="card">
          <h3>Universe</h3>
          {list.length === 0 ? (
            <p className="empty">Import or fetch data to see symbols.</p>
          ) : (
            <div className="table-wrap">
              <table>
                <thead>
                  <tr>
                    <th>Symbol</th>
                    <th>Yahoo</th>
                    <th>CCY</th>
                  </tr>
                </thead>
                <tbody>
                  {list.map((i) => (
                    <tr
                      key={i.id}
                      onClick={() => select(i)}
                      style={{
                        cursor: "pointer",
                        background:
                          selected?.id === i.id
                            ? "rgba(0,113,227,0.06)"
                            : undefined,
                      }}
                    >
                      <td>
                        <strong>{i.symbol}</strong>
                      </td>
                      <td className="mono">{i.yahoo_symbol}</td>
                      <td>{i.currency_quoted}</td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          )}
        </div>

        <div className="card">
          <h3>{selected ? selected.yahoo_symbol : "Chart"}</h3>
          {!bars?.daily?.length ? (
            <p className="empty">Select a stock to preview closes.</p>
          ) : (
            <>
              <div
                style={{
                  display: "flex",
                  alignItems: "flex-end",
                  gap: 2,
                  height: 160,
                  marginTop: "1rem",
                }}
              >
                {closes.slice(-60).map((c, idx) => (
                  <div
                    key={idx}
                    title={String(c)}
                    style={{
                      flex: 1,
                      height: `${((c - min) / span) * 100}%`,
                      minHeight: 4,
                      background: "#0071e3",
                      borderRadius: 2,
                      opacity: 0.75,
                      transition: "height 0.35s cubic-bezier(0.25,0.1,0.25,1)",
                    }}
                  />
                ))}
              </div>
              <p style={{ marginTop: "0.75rem" }}>
                Last close{" "}
                <strong>£{closes[closes.length - 1]?.toFixed(4)}</strong> ·{" "}
                {bars.daily.length} sessions
              </p>
            </>
          )}
        </div>
      </div>
    </div>
  );
}
