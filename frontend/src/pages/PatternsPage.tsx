import { useEffect, useState } from "react";
import { apiGet } from "../api/client";

type Pattern = {
  kind: string;
  claim: string;
  status: string;
  sample_size: number | null;
  evidence_label: string;
  note: string;
};

export function PatternsPage() {
  const [patterns, setPatterns] = useState<Pattern[]>([]);
  const [note, setNote] = useState("");

  useEffect(() => {
    apiGet<{ patterns: Pattern[]; note: string }>("/patterns").then((r) => {
      setPatterns(r.patterns);
      setNote(r.note);
    });
  }, []);

  return (
    <div>
      <header className="page-head">
        <h1>Patterns</h1>
        <p>
          Hypotheses with sample sizes. Exploratory is not validated —
          synthetic demos stay labelled.
        </p>
      </header>
      {note && <div className="banner info">{note}</div>}
      <div className="grid" style={{ gap: "0.85rem" }}>
        {!patterns.length && (
          <div className="card">
            <p className="empty">No patterns yet. Train and resolve forecasts first.</p>
          </div>
        )}
        {patterns.map((p, i) => (
          <div className="card" key={`${p.kind}-${i}`}>
            <span
              className={`pill ${
                p.evidence_label === "validated"
                  ? "green"
                  : p.evidence_label === "synthetic"
                    ? "amber"
                    : "blue"
              }`}
            >
              {p.evidence_label}
            </span>
            <span className="pill">{p.kind}</span>
            <h3 style={{ marginTop: "0.65rem", fontWeight: 500 }}>{p.claim}</h3>
            <p style={{ marginTop: "0.5rem" }}>
              n={p.sample_size ?? "—"} · {p.note}
            </p>
          </div>
        ))}
      </div>
    </div>
  );
}
