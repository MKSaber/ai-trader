import { useEffect, useState } from "react";
import { apiGet } from "../api/client";

type Finding = {
  id: number;
  claim: string;
  status: string;
  discovery_date: string;
  data_cutoff: string;
  sample_size: number | null;
  effect_size: number | null;
  topic: string | null;
  note: string;
};

export function FindingsPage() {
  const [rows, setRows] = useState<Finding[]>([]);
  const [q, setQ] = useState("");

  useEffect(() => {
    const path = q ? `/findings?q=${encodeURIComponent(q)}` : "/findings";
    apiGet<Finding[]>(path).then(setRows);
  }, [q]);

  return (
    <div>
      <header className="page-head">
        <h1>Findings</h1>
        <p>
          Stored claims with evidence — not established truth. Search and review
          status before acting.
        </p>
      </header>

      <div className="actions left">
        <input
          className="select"
          style={{ minWidth: "220px", borderRadius: "12px" }}
          placeholder="Search findings"
          value={q}
          onChange={(e) => setQ(e.target.value)}
        />
      </div>

      <div className="grid" style={{ gap: "0.85rem" }}>
        {rows.length === 0 && (
          <div className="card">
            <p className="empty">No findings yet. Run the daily pipeline.</p>
          </div>
        )}
        {rows.map((f) => (
          <div className="card" key={f.id}>
            <div style={{ marginBottom: "0.5rem" }}>
              <span
                className={`pill ${
                  f.status === "validated"
                    ? "green"
                    : f.status === "contradicted"
                      ? "red"
                      : "amber"
                }`}
              >
                {f.status}
              </span>
              {f.topic && <span className="pill">{f.topic}</span>}
            </div>
            <h3 style={{ fontSize: "1.05rem", fontWeight: 500 }}>{f.claim}</h3>
            <p style={{ marginTop: "0.65rem" }}>
              Discovered {f.discovery_date} · cutoff {f.data_cutoff}
              {f.sample_size != null ? ` · n=${f.sample_size}` : ""}
            </p>
            <p style={{ marginTop: "0.35rem", fontSize: "0.85rem" }}>
              {f.note}
            </p>
          </div>
        ))}
      </div>
    </div>
  );
}
