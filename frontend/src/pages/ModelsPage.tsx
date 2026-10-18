import { useEffect, useState } from "react";
import { apiGet, apiPost } from "../api/client";

type Model = {
  id: number;
  version: string;
  model_type: string;
  status: string;
  formula: Record<string, unknown> | null;
  feature_importance: Record<string, number> | null;
  metrics: Record<string, unknown> | null;
  horizon: string;
};

export function ModelsPage() {
  const [rows, setRows] = useState<Model[]>([]);
  const [openId, setOpenId] = useState<number | null>(null);

  const load = () => apiGet<Model[]>("/models").then(setRows);
  useEffect(() => {
    load();
  }, []);

  return (
    <div>
      <header className="page-head">
        <h1>Models</h1>
        <p>
          Read the formula. Compare candidates. Promote only with intent —
          never automatically from the daily pipeline.
        </p>
      </header>

      <div className="actions left">
        <button
          onClick={async () => {
            await apiPost("/research/train");
            load();
          }}
        >
          Train models
        </button>
      </div>

      <div className="grid" style={{ gap: "0.85rem" }}>
        {rows.length === 0 && (
          <div className="card">
            <p className="empty">No models yet.</p>
          </div>
        )}
        {rows.map((m) => {
          const open = openId === m.id;
          return (
            <div className="card" key={m.id} style={{ cursor: "pointer" }}>
              <div
                onClick={() => setOpenId(open ? null : m.id)}
                style={{
                  display: "flex",
                  justifyContent: "space-between",
                  alignItems: "center",
                  gap: "1rem",
                }}
              >
                <div>
                  <h3 style={{ marginBottom: "0.35rem" }}>
                    {m.model_type}{" "}
                    <span
                      className={`pill ${
                        m.status === "champion" ? "blue" : ""
                      }`}
                    >
                      {m.status}
                    </span>
                  </h3>
                  <div className="mono">{m.version}</div>
                </div>
                <span className="pill">{open ? "Hide" : "Details"}</span>
              </div>

              {open && (
                <div style={{ marginTop: "1rem" }}>
                  <p style={{ marginBottom: "0.5rem" }}>
                    Horizon: {m.horizon}
                  </p>
                  {m.formula && (
                    <pre className="mono">
                      {JSON.stringify(m.formula, null, 2)}
                    </pre>
                  )}
                  {m.feature_importance && (
                    <pre className="mono">
                      {JSON.stringify(m.feature_importance, null, 2)}
                    </pre>
                  )}
                  {m.metrics && (
                    <pre className="mono">
                      {JSON.stringify(m.metrics, null, 2)}
                    </pre>
                  )}
                  {m.status !== "champion" && (
                    <div className="actions left" style={{ marginTop: "1rem" }}>
                      <button
                        onClick={async (e) => {
                          e.stopPropagation();
                          await apiPost("/models/promote", {
                            model_id: m.id,
                            approve: true,
                          });
                          load();
                        }}
                      >
                        Make champion
                      </button>
                      <button
                        className="secondary"
                        onClick={async (e) => {
                          e.stopPropagation();
                          await apiPost("/models/promote", {
                            model_id: m.id,
                            approve: false,
                          });
                          load();
                        }}
                      >
                        Reject
                      </button>
                      {(m.status === "retired" || m.status === "candidate") && (
                        <button
                          className="secondary"
                          onClick={async (e) => {
                            e.stopPropagation();
                            await apiPost("/models/rollback", {
                              model_id: m.id,
                            });
                            load();
                          }}
                        >
                          Rollback to this
                        </button>
                      )}
                    </div>
                  )}
                </div>
              )}
            </div>
          );
        })}
      </div>
    </div>
  );
}
