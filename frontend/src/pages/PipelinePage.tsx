import { useEffect, useState } from "react";
import { apiGet, apiPost } from "../api/client";

type Run = {
  id: number;
  run_key: string;
  session_date: string | null;
  status: string;
  offline: boolean;
  dry_run: boolean;
  started_at: string | null;
  error_summary: string | null;
};

export function PipelinePage() {
  const [rows, setRows] = useState<Run[]>([]);
  const [busy, setBusy] = useState(false);
  const [last, setLast] = useState("");

  const load = () => apiGet<Run[]>("/pipeline/runs").then(setRows);
  useEffect(() => {
    load();
  }, []);

  return (
    <div>
      <header className="page-head">
        <h1>Pipeline</h1>
        <p>
          Daily research runs without the dashboard. Ingest, evaluate, recommend
          — never auto-trade or auto-promote.
        </p>
      </header>

      <div className="actions left">
        <button
          disabled={busy}
          onClick={async () => {
            setBusy(true);
            try {
              const r = await apiPost<Record<string, unknown>>("/pipeline/run", {
                offline: false,
              });
              setLast(JSON.stringify(r, null, 2));
              await load();
            } catch (e) {
              setLast(String(e));
            } finally {
              setBusy(false);
            }
          }}
        >
          {busy ? "Running…" : "Run with Yahoo"}
        </button>
        <button
          className="secondary"
          disabled={busy}
          onClick={async () => {
            setBusy(true);
            try {
              const r = await apiPost<Record<string, unknown>>("/pipeline/run", {
                offline: true,
              });
              setLast(JSON.stringify(r, null, 2));
              await load();
            } catch (e) {
              setLast(String(e));
            } finally {
              setBusy(false);
            }
          }}
        >
          Run offline (sample)
        </button>
      </div>

      {last && (
        <div className="card" style={{ marginBottom: "1.1rem" }}>
          <h3>Last result</h3>
          <pre className="mono">{last}</pre>
        </div>
      )}

      <div className="card">
        <h3>Recent runs</h3>
        {!rows.length ? (
          <p className="empty">No pipeline runs yet.</p>
        ) : (
          <div className="table-wrap">
            <table>
              <thead>
                <tr>
                  <th>Run</th>
                  <th>Session</th>
                  <th>Status</th>
                  <th>Mode</th>
                </tr>
              </thead>
              <tbody>
                {rows.map((r) => (
                  <tr key={r.id}>
                    <td className="mono">{r.run_key}</td>
                    <td>{r.session_date ?? "—"}</td>
                    <td>
                      <span
                        className={`pill ${
                          r.status === "success"
                            ? "green"
                            : r.status === "failed"
                              ? "red"
                              : "amber"
                        }`}
                      >
                        {r.status}
                      </span>
                    </td>
                    <td>
                      {r.offline ? "offline" : "live"}
                      {r.dry_run ? " · dry-run" : ""}
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
