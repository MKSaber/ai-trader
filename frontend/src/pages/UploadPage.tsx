import { useEffect, useRef, useState } from "react";
import { apiGet, apiUpload } from "../api/client";

type UploadRow = {
  id: number;
  filename: string;
  source_type: string;
  status: string;
  warnings?: string[];
};

export function UploadPage() {
  const [rows, setRows] = useState<UploadRow[]>([]);
  const [sourceType, setSourceType] = useState("market_ohlcv");
  const [drag, setDrag] = useState(false);
  const [status, setStatus] = useState("");
  const inputRef = useRef<HTMLInputElement>(null);

  const refresh = () =>
    apiGet<UploadRow[]>("/uploads")
      .then(setRows)
      .catch((e) => setStatus(String(e)));

  useEffect(() => {
    refresh();
  }, []);

  async function handleFiles(files: FileList | null) {
    const file = files?.[0];
    if (!file) return;
    setStatus("Uploading…");
    try {
      const res = await apiUpload(file, sourceType);
      setStatus(JSON.stringify(res, null, 2));
      refresh();
    } catch (e) {
      setStatus(String(e));
    }
  }

  return (
    <div>
      <header className="page-head">
        <h1>Import</h1>
        <p>
          Drop a file. We validate type, size, and duplicates — and never treat
          uploads as executable instructions.
        </p>
      </header>

      <div
        className={`dropzone${drag ? " dragover" : ""}`}
        onClick={() => inputRef.current?.click()}
        onDragOver={(e) => {
          e.preventDefault();
          setDrag(true);
        }}
        onDragLeave={() => setDrag(false)}
        onDrop={(e) => {
          e.preventDefault();
          setDrag(false);
          handleFiles(e.dataTransfer.files);
        }}
      >
        <strong>Drop CSV, XLSX, PDF, or TXT</strong>
        <span>or click to browse · max size from settings</span>
        <div>
          <select
            className="select"
            value={sourceType}
            onClick={(e) => e.stopPropagation()}
            onChange={(e) => setSourceType(e.target.value)}
          >
            <option value="market_ohlcv">Market OHLCV</option>
            <option value="executed_trades">Executed trades</option>
            <option value="narrative">Narrative commentary</option>
          </select>
        </div>
        <input
          ref={inputRef}
          type="file"
          accept=".csv,.xlsx,.xls,.pdf,.txt"
          onChange={(e) => handleFiles(e.target.files)}
        />
      </div>

      {status && (
        <div className="card" style={{ marginTop: "1.25rem" }}>
          <h3>Status</h3>
          <pre className="mono">{status}</pre>
        </div>
      )}

      <div className="card" style={{ marginTop: "1.25rem" }}>
        <h3>Recent imports</h3>
        {rows.length === 0 ? (
          <p className="empty">Nothing imported yet.</p>
        ) : (
          <div className="table-wrap">
            <table>
              <thead>
                <tr>
                  <th>File</th>
                  <th>Type</th>
                  <th>Status</th>
                </tr>
              </thead>
              <tbody>
                {rows.map((r) => (
                  <tr key={r.id}>
                    <td>{r.filename}</td>
                    <td>{r.source_type}</td>
                    <td>
                      <span
                        className={`pill ${
                          r.status === "needs_ocr"
                            ? "amber"
                            : r.status === "failed"
                              ? "red"
                              : "green"
                        }`}
                      >
                        {r.status}
                      </span>
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
