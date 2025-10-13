# Paper Trading Mode

This document describes the production-grade paper trading pipeline and how to calibrate it to match live execution.

## What Is Simulated

- **Order-book microstructure** – limit orders rest on the book with a configurable slice plan. Queue position is approximated by simulating trade consumption and order-flow imbalance (OFI) pressure.
- **Market/Stop orders** – marketables cross the spread immediately with configurable slippage; stop-orders trigger on composite mid-price and execute reduce-only market orders.
- **Latency distribution** – acknowledgements and fills are delayed according to `latency_ms.{mean,p95,jitter}` using a Gaussian sampler with clamping at zero.
- **Fees & funding** – maker rebates / taker fees apply per fill, and hourly/8h funding accrues when `funding_enabled` is set.
- **Risk & liquidation guardrails** - position sizing, margin, and liquidation distance are tracked so paper accounts respect risk policy (liquidation >= 4x configured stop distance).
- **Persistence & observability** - every fill records achieved price, mark-to-market, slippage bps, maker/taker flag, latency_ms, and is tagged with `{mode, run_id}`. Metrics for slippage, maker ratio, and signal->ack latency are exported via Prometheus.

## Limitations vs Live

- Queue modelling uses a depth/OFI proxy rather than exchange-provided order book IDs; extremely fast-moving markets can deviate.
- Market impact beyond L1/L2 depth is approximated; there is no explicit sweep across deeper levels.
- Liquidation is simulated using static margin rules – venue-specific quirks (ADL, partial liquidation) are not reproduced.
- External exchange-side throttles (rate limits, web-socket disconnects) are not emulated.

## Tuning Paper Parameters

1. **Inspect current settings**

   ```bash
   curl http://localhost:8082/api/paper/config
   ```

   Update fields via `POST /api/paper/config` or by editing `config/strategy.yaml` (`paper.*` and `replay.*`).

2. **Collect calibration runs**

   - In paper-only testing, run deterministic replays (`paper.price_source: "replay"`) with the bundled dataset `parquet://sample_data/btc_eth_4h.parquet`.
   - In live trading, enable `shadow_paper` to generate parallel paper fills. The dashboard “Paper vs Live” panel and Prometheus metrics expose divergence in achieved slippage, PF, expectancy, and maker ratio.

3. **Iterate**

   Adjust `slippage_bps`, `spread_slippage_coeff`, `ofi_slippage_coeff`, `latency_ms`, and partial-fill settings until live vs. shadow deviations stay within tolerance. Re-run calibration workflows after any exchange microstructure change.
