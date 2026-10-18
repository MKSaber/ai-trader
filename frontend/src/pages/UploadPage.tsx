import { useEffect, useRef, useState } from "react";
import { apiGet, apiPost, apiUpload } from "../api/client";

const API_BASE = import.meta.env.VITE_API_BASE || "/api";

const DEFAULT_SYMBOLS = "VOD.L,BP.L,HSBA.L,GSK.L,AZN.L";

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
  const [symbols, setSymbols] = useState(DEFAULT_SYMBOLS);
  const [fetching, setFetching] = useState(false);
  const inputRef = useRef<HTMLInputElement>(null);

  const refresh = () =>
    apiGet<UploadRow[]>("/uploads")
      .then(setRows)
      .catch((e) => setStatus(String(e)));

  useEffect(() => {
    refresh();
  }, []);

  async function fetchYahoo() {
    setFetching(true);
    setStatus("Fetching from Yahoo Finance…");
    try {
      const qs = new URLSearchParams({
        offline: "false",
        lookback_days: "1825",
        symbols: symbols.trim() || DEFAULT_SYMBOLS,
      });
      const res = await apiPost<Record<string, unknown>>(
        `/provider/fetch?${qs.toString()}`,
      );
      setStatus(JSON.stringify(res, null, 2));
    } catch (e) {
      setStatus(String(e));
    } finally {
      setFetching(false);
    }
  }

  async function preview(file: File) {
    const form = new FormData();
    form.append("file", file);
    const res = await fetch(`${API_BASE}/uploads/preview`, {
      method: "POST",
      body: form,
    });
    if (!res.ok) throw new Error(await res.text());
    return res.json();
  }

  async function handleFiles(files: FileList | null) {
    const file = files?.[0];
    if (!file) return;
    setStatus("Previewing…");
    try {
      if (
        sourceType === "market_ohlcv" &&
        /\.(csv|xlsx|xls)$/i.test(file.name)
      ) {
        const map = await preview(file);
        setStatus(
          `Mapping preview:\n${JSON.stringify(map, null, 2)}\n\nImporting…`,
        );
      }
      const res = await apiUpload(file, sourceType);
      setStatus(
        (prev) => `${prev}\n\nImport:\n${JSON.stringify(res, null, 2)}`,
      );
      refresh();
    } catch (e) {
      setStatus(String(e));
    }
  }

  return (
    <div>
      <header className="page-head">
        <h1>Market data</h1>
        <p>
          Pull LSE bars from Yahoo Finance (via yfinance). File upload stays
          available for trades and commentary — not required for prices.
        </p>
      </header>

      <div className="card" style={{ marginBottom: "1.25rem" }}>
        <h3>Fetch from Yahoo</h3>
        <p style={{ color: "var(--secondary)", marginTop: 0 }}>
          Pulls ~5 years of daily bars by default for walk-forward training.
          Intraday remains ~60 days. Empty responses are never replaced with
          synthetic data.
        </p>
        <label
          style={{
            display: "block",
            fontSize: "0.85rem",
            color: "var(--secondary)",
            marginBottom: "0.35rem",
          }}
        >
          Symbols (Yahoo format, comma-separated)
        </label>
        <input
          className="select"
          style={{ width: "100%", maxWidth: "36rem", marginBottom: "1rem" }}
          value={symbols}
          onChange={(e) => setSymbols(e.target.value)}
          placeholder={DEFAULT_SYMBOLS}
        />
        <div className="actions left">
          <button disabled={fetching} onClick={fetchYahoo}>
            {fetching ? "Fetching…" : "Fetch 5y from Yahoo"}
          </button>
          <button
            className="secondary"
            disabled={fetching}
            onClick={async () => {
              setFetching(true);
              setStatus("Loading sample fixtures…");
              try {
                const res = await apiPost("/provider/fetch?offline=true");
                setStatus(JSON.stringify(res, null, 2));
              } catch (e) {
                setStatus(String(e));
              } finally {
                setFetching(false);
              }
            }}
          >
            Use sample data
          </button>
        </div>
      </div>

      <header className="page-head" style={{ marginTop: "0.5rem" }}>
        <h1 style={{ fontSize: "1.35rem" }}>Optional file import</h1>
        <p>
          Drop a file for custom OHLCV, executed trades, or narrative notes.
          Uploads are validated and never treated as executable instructions.
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
