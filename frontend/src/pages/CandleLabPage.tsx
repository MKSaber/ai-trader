/**
 * Non-interfering shell: embeds the independent Live Candle Pattern Test app.
 * Does not call Pattern Lab research/train APIs or share its database.
 */
export function CandleLabPage() {
  const src =
    import.meta.env.VITE_CANDLE_LAB_URL || "http://localhost:3100";

  return (
    <div>
      <header className="page-head">
        <h1>Candle patterns</h1>
        <p>
          Delayed candlestick detection and paper setups — isolated from
          Pattern Lab models and Postgres.
        </p>
      </header>
      <div className="card" style={{ padding: 0, overflow: "hidden" }}>
        <iframe
          title="Live Candle Pattern Test"
          src={src}
          style={{
            width: "100%",
            height: "min(85vh, 920px)",
            border: 0,
            display: "block",
            background: "var(--bg)",
          }}
        />
      </div>
      <p className="footer-note" style={{ marginTop: "1rem" }}>
        If blank: start <code>candle-lab</code> API :8100 and UI :3100
      </p>
    </div>
  );
}
