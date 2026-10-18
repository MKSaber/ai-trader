import { useEffect, useState } from "react";
import { apiGet, apiPost } from "../api/client";

type Coverage = {
  instruments: number;
  daily_bars: number;
  intraday_bars: number;
  warnings: string[];
};

export function CoveragePage() {
  const [data, setData] = useState<Coverage | null>(null);
  const [busy, setBusy] = useState(false);
  const [note, setNote] = useState("");

  const load = () => apiGet<Coverage>("/coverage").then(setData);

  useEffect(() => {
    load().catch(() => setData(null));
  }, []);

  async function fetchYahoo() {
    setBusy(true);
    setNote("");
    try {
      const res = await apiPost<Record<string, unknown>>(
        "/provider/fetch?offline=false&lookback_days=1825&symbols=VOD.L,BP.L,HSBA.L,GSK.L,AZN.L",
      );
      setNote(JSON.stringify(res, null, 2));
      await load();
    } catch (e) {
      setNote(String(e));
    } finally {
      setBusy(false);
    }
  }

  return (
    <div>
      <header className="page-head">
        <h1>Coverage</h1>
        <p>
          What we have — and what we still need before making claims.
        </p>
      </header>

      <div className="actions left" style={{ marginBottom: "1.25rem" }}>
        <button disabled={busy} onClick={fetchYahoo}>
          {busy ? "Fetching…" : "Fetch 5y from Yahoo"}
        </button>
      </div>

      {data?.warnings?.map((w) => (
        <div className="banner" key={w}>
          {w}
        </div>
      ))}

      <div className="grid grid-3">
        {[
          ["Instruments", data?.instruments],
          ["Daily bars", data?.daily_bars],
          ["Intraday bars", data?.intraday_bars],
        ].map(([label, value]) => (
          <div className="card stat" key={String(label)}>
            <div className="value">{value ?? "—"}</div>
            <div className="label">{label}</div>
          </div>
        ))}
      </div>

      {note && (
        <div className="card" style={{ marginTop: "1.25rem" }}>
          <h3>Last fetch</h3>
          <pre className="mono">{note}</pre>
        </div>
      )}
    </div>
  );
}
