# UK share dealing cost sources (candle-lab)

Figures used by broker cost profiles in `backend/app/config.py` /
`backend/app/paper.py`. Verified against primary pages (accessed for this
experiment). Brokers change fees — re-check before relying on results.

## Government / panel (not broker fees)

| Item | Rate | When | Source |
|------|------|------|--------|
| Stamp Duty Reserve Tax (SDRT) | **0.5%** of consideration | Electronic purchase of UK shares (CREST) | [GOV.UK — buy shares electronically](https://www.gov.uk/tax-buy-shares/buy-shares-electronically); [HMRC STSM014010](https://www.gov.uk/hmrc-internal-manuals/stamp-taxes-shares-manual/stsm014010) |
| Higher SDRT | 1.5% | Into some depositary-receipt / clearance schemes (not normal broker CREST buys) | [GOV.UK — tax when you buy shares](https://www.gov.uk/tax-buy-shares) |
| PTM levy | **£1.50** per contract | Buy **and** sell when consideration **> £10,000** | [The Takeover Panel — PTM Levy](https://www.thetakeoverpanel.org.uk/disclosure/ptm-levy) (rate raised from £1.00 → £1.50 from **2 Dec 2024**) |

SDRT does **not** apply on sales. AIM stocks are often exempt (broker notes);
our five names (VOD, BP, HSBA, GSK, AZN) are main-market — SDRT applies.

## Trading 212 — Invest / Stocks ISA / SIPP (UK)

From [Trading 212 help — Invest/ISA/SIPP fees](https://helpcentre.trading212.com/hc/en-us/articles/11471996799517-What-are-the-fees-in-the-Invest-ISAs-and-SIPP):

| Item | Amount |
|------|--------|
| Trading commission | **Free** |
| Custody | **Free** |
| FX fee | **0.15%** only when currency conversion is needed |
| LSE SDRT | **0.5%** on purchases (passed through) |
| PTM levy | **£1.50** buy and sell when order **> £10,000** |

For **GBP account buying LSE GBP shares** (our backtest case): model **commission = 0**, **FX = 0**, plus SDRT + PTM.

Also: [Costs & Charges Disclosure (PDF)](https://www.trading212.com/legal-documentation/uk/common/Costs-and-Charges-Disclosure_EN.pdf) (PTM wording there still says £1 in places — Panel primary source is £1.50 from Dec 2024; T212 help centre matches £1.50).

## eToro — real stocks (not CFDs)

From [eToro fees](https://www.etoro.com/trading/fees/):

| Item | Amount |
|------|--------|
| Custody | **Free** |
| SDRT on UK-listed stocks | **0.5%** on opening a new real-stock position (passed to HMRC) |
| Market spread | Bid/ask from the market; eToro states **no spread markup** |
| Stock commission | **$1 or $2** open/close depending on residence **and** exchange (see live fee table on that page) |
| Stock Margin | Separate product: **0.15%** commission each way + overnight on borrowed amount |

UK marketing / press has also described **UK stocks & ETFs on a GBP account as commission-free** (FX removed for local assets). The live fee table is residence/exchange-specific — our `etoro_uk_lse` profile assumes **£0 commission** for UK-resident GBP account trading LSE cash equities; use `etoro_flat_usd` if you want an explicit $1/$2 flat each way.

CFD / leveraged stock positions: **no SDRT**, but CFD spreads + overnight — **out of scope** for this cash long-only lab.

## What we still assume (not a published broker fee)

| Item | Default in broker profiles | Why |
|------|----------------------------|-----|
| Quoted market spread | 5 bps | Liquid FTSE names still have a bid/ask; not charged by T212/eToro as a line item |
| Slippage | 2 bps | Adverse fill vs mid on 5m bars; experiment assumption |

Legacy profile (`legacy_stress`) keeps the older 5 / 10 / 5 bps stack for comparison with earlier runs.
