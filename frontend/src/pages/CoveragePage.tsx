import { useEffect, useState } from "react";
import { apiGet } from "../api/client";

type Coverage = {
  instruments: number;
  daily_bars: number;
  intraday_bars: number;
  warnings: string[];
};

export function CoveragePage() {
  const [data, setData] = useState<Coverage | null>(null);

  useEffect(() => {
    apiGet<Coverage>("/coverage").then(setData);
  }, []);

  return (
    <div>
      <header className="page-head">
        <h1>Coverage</h1>
        <p>
          What we have — and what we still need before making claims.
        </p>
      </header>

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
    </div>
  );
}
