import { useEffect, useState } from "react";
import { apiGet } from "../api/client";

type Drift = {
  status: string;
  message?: string;
  alerts: Array<{ feature: string; severity: string; message: string }>;
  comparisons?: Record<string, unknown>;
  note?: string;
};

export function DriftPage() {
  const [data, setData] = useState<Drift | null>(null);

  useEffect(() => {
    apiGet<Drift>("/drift").then(setData);
  }, []);

  return (
    <div>
      <header className="page-head">
        <h1>Drift</h1>
        <p>
          Feature and forecast shifts trigger investigation — never automatic
          deployment.
        </p>
      </header>
      {data?.message && <div className="banner">{data.message}</div>}
      {data?.alerts?.map((a) => (
        <div
          className={`banner ${a.severity === "high" ? "danger" : ""}`}
          key={a.feature + a.message}
        >
          {a.message}
        </div>
      ))}
      {data?.status === "ok" && !data.alerts?.length && (
        <div className="banner info">No material drift alerts right now.</div>
      )}
      {data?.comparisons && (
        <div className="card">
          <h3>Comparisons</h3>
          <pre className="mono">{JSON.stringify(data.comparisons, null, 2)}</pre>
          <p style={{ marginTop: "0.75rem" }}>{data.note}</p>
        </div>
      )}
    </div>
  );
}
