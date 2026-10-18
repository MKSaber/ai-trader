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
          Separate application for live/delayed candlestick detection and
          paper setups. Isolated from Pattern Lab models and Postgres.
        </p>
      </header>
      <div
        style={{
          borderRadius: 16,
          overflow: "hidden",
          border: "1px solid var(--line)",
          background: "#0f1419",
          minHeight: "75vh",
        }}
      >
        <iframe
          title="Live Candle Pattern Test"
          src={src}
          style={{
            width: "100%",
            height: "75vh",
            border: 0,
            display: "block",
          }}
        />
      </div>
      <p
        style={{
          marginTop: "0.75rem",
          fontSize: "0.85rem",
          color: "var(--secondary)",
        }}
      >
        If the frame is blank, start candle-lab:{" "}
        <code>candle-lab/backend</code> on :8100 and{" "}
        <code>candle-lab/frontend</code> on :3100. See{" "}
        <code>candle-lab/README.md</code>.
      </p>
    </div>
  );
}
