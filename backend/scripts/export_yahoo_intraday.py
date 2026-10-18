"""Export recent Yahoo Finance 5-minute bars for an LSE symbol.

Prototype / personal research use only. Review Yahoo terms before
redistribution. Intraday history typically cannot exceed ~60 days.
"""

from __future__ import annotations

import argparse

import yfinance as yf


def main() -> None:
    """Download and write CSV."""
    parser = argparse.ArgumentParser()
    parser.add_argument("--symbol", default="VOD.L")
    parser.add_argument("--out", default="VOD_L_5min.csv")
    parser.add_argument("--period", default="1mo")
    args = parser.parse_args()

    data = yf.Ticker(args.symbol).history(
        period=args.period,
        interval="5m",
        auto_adjust=False,
        actions=False,
        prepost=False,
    )
    if data.empty:
        raise RuntimeError(f"No intraday data returned for {args.symbol}")
    data.to_csv(args.out)
    print(f"Exported {len(data)} bars to {args.out}")
    print(
        "Note: unofficial Yahoo integration; not a production feed; "
        "insufficient alone to establish a trading edge."
    )


if __name__ == "__main__":
    main()
