"""Exchange API Latency Benchmark

Measures round-trip latency to exchange APIs from the current host.
Run on both local and VPS machines to compare.

Usage:
    python tools/latency_bench.py                      # Default: Bybit, 20 pings
    python tools/latency_bench.py --exchange binance    # Binance
    python tools/latency_bench.py --runs 50 --json      # 50 runs, JSON output
    python tools/latency_bench.py --compare local.json vps.json

Supported exchanges: bybit, binance, okx, coinbase, kraken
"""

import argparse
import asyncio
import json
import math
import statistics
import sys
import time
from dataclasses import asdict, dataclass
from typing import Optional

import httpx


# ── Exchange endpoints ────────────────────────────────────────────────

ENDPOINTS: dict[str, dict[str, str]] = {
    "bybit": {
        "rest": "https://api.bybit.com/v5/market/time",
        "label": "Bybit (REST)",
    },
    "binance": {
        "rest": "https://api.binance.com/api/v3/time",
        "label": "Binance (REST)",
    },
    "okx": {
        "rest": "https://www.okx.com/api/v5/public/time",
        "label": "OKX (REST)",
    },
    "coinbase": {
        "rest": "https://api.exchange.coinbase.com/time",
        "label": "Coinbase (REST)",
    },
    "kraken": {
        "rest": "https://api.kraken.com/0/public/Time",
        "label": "Kraken (REST)",
    },
}


# ── Data model ────────────────────────────────────────────────────────


@dataclass
class BenchmarkResult:
    exchange: str
    endpoint: str
    runs: int
    latencies_ms: list[float]
    min_ms: float
    max_ms: float
    mean_ms: float
    median_ms: float
    p95_ms: float
    p99_ms: float
    stdev_ms: float
    errors: int
    timestamp: float
    hostname: str


def percentile(data: list[float], p: float) -> float:
    """Calculate percentile from sorted data."""
    if not data:
        return 0.0
    sorted_data = sorted(data)
    k = (len(sorted_data) - 1) * (p / 100)
    f = math.floor(k)
    c = math.ceil(k)
    if f == c:
        return sorted_data[int(k)]
    return sorted_data[f] * (c - k) + sorted_data[c] * (k - f)


# ── Benchmark runner ──────────────────────────────────────────────────


async def benchmark_exchange(
    exchange: str, runs: int = 20
) -> BenchmarkResult:
    """Measure round-trip latency to an exchange API endpoint."""
    import socket

    endpoint_info = ENDPOINTS.get(exchange)
    if not endpoint_info:
        raise ValueError(
            f"Unknown exchange: {exchange}. Options: {', '.join(ENDPOINTS)}"
        )

    url = endpoint_info["rest"]
    label = endpoint_info["label"]
    latencies: list[float] = []
    errors = 0

    print(f"\n  Benchmarking {label}")
    print(f"  Endpoint: {url}")
    print(f"  Runs: {runs}")
    print(f"  {'─' * 40}")

    async with httpx.AsyncClient(timeout=15, http2=True) as client:
        # Warm-up request (not counted)
        try:
            await client.get(url)
        except Exception:
            pass

        for i in range(runs):
            try:
                start = time.perf_counter()
                resp = await client.get(url)
                elapsed = (time.perf_counter() - start) * 1000  # ms

                if resp.status_code == 200:
                    latencies.append(elapsed)
                    bar = "█" * int(elapsed / 5) if elapsed < 500 else "█" * 100
                    print(f"  [{i+1:3d}/{runs}] {elapsed:7.1f} ms  {bar}")
                else:
                    errors += 1
                    print(f"  [{i+1:3d}/{runs}] HTTP {resp.status_code}")
            except Exception as e:
                errors += 1
                print(f"  [{i+1:3d}/{runs}] Error: {e}")

            # Small delay between requests to avoid rate limiting
            await asyncio.sleep(0.2)

    if not latencies:
        latencies = [0.0]

    return BenchmarkResult(
        exchange=exchange,
        endpoint=url,
        runs=runs,
        latencies_ms=latencies,
        min_ms=min(latencies),
        max_ms=max(latencies),
        mean_ms=statistics.mean(latencies),
        median_ms=statistics.median(latencies),
        p95_ms=percentile(latencies, 95),
        p99_ms=percentile(latencies, 99),
        stdev_ms=statistics.stdev(latencies) if len(latencies) > 1 else 0.0,
        errors=errors,
        timestamp=time.time(),
        hostname=socket.gethostname(),
    )


def print_results(result: BenchmarkResult) -> None:
    """Display benchmark results as a formatted table."""
    print(f"\n  ══════════════════════════════════════════")
    print(f"  Results: {result.exchange} from {result.hostname}")
    print(f"  ──────────────────────────────────────────")
    print(f"  Successful:  {result.runs - result.errors}/{result.runs}")
    print(f"  Min:         {result.min_ms:7.1f} ms")
    print(f"  Max:         {result.max_ms:7.1f} ms")
    print(f"  Mean:        {result.mean_ms:7.1f} ms")
    print(f"  Median:      {result.median_ms:7.1f} ms")
    print(f"  P95:         {result.p95_ms:7.1f} ms")
    print(f"  P99:         {result.p99_ms:7.1f} ms")
    print(f"  Stdev:       {result.stdev_ms:7.1f} ms")
    print(f"  Errors:      {result.errors}")
    print(f"  ══════════════════════════════════════════\n")


# ── Comparison ────────────────────────────────────────────────────────


def compare_results(file_a: str, file_b: str) -> None:
    """Compare two saved benchmark results side by side."""
    with open(file_a) as f:
        a = json.load(f)
    with open(file_b) as f:
        b = json.load(f)

    print(f"\n  ═══ Latency Comparison ═══")
    print(f"  {'Metric':<12} {'Local':>12} {'VPS':>12} {'Delta':>12} {'Winner':>10}")
    print(f"  {'─' * 60}")

    metrics = [
        ("Min", "min_ms"),
        ("Max", "max_ms"),
        ("Mean", "mean_ms"),
        ("Median", "median_ms"),
        ("P95", "p95_ms"),
        ("P99", "p99_ms"),
        ("Stdev", "stdev_ms"),
    ]

    for label, key in metrics:
        va = a.get(key, 0)
        vb = b.get(key, 0)
        delta = vb - va
        winner = "VPS" if vb < va else ("Local" if va < vb else "Tie")
        arrow = "↓" if vb < va else ("↑" if va < vb else "=")
        print(
            f"  {label:<12} {va:>9.1f} ms {vb:>9.1f} ms {delta:>+9.1f} ms {arrow} {winner:>6}"
        )

    print(f"  {'─' * 60}")
    print(f"  Host A: {a.get('hostname', '?')}")
    print(f"  Host B: {b.get('hostname', '?')}")
    print()


# ── Main ──────────────────────────────────────────────────────────────


async def main() -> int:
    parser = argparse.ArgumentParser(
        description="Exchange API latency benchmark",
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    parser.add_argument(
        "--exchange",
        default="bybit",
        choices=list(ENDPOINTS.keys()),
        help="Exchange to benchmark (default: bybit)",
    )
    parser.add_argument(
        "--runs", type=int, default=20, help="Number of requests (default: 20)"
    )
    parser.add_argument(
        "--json", action="store_true", help="Output raw JSON to stdout"
    )
    parser.add_argument(
        "--output", type=str, help="Save results to JSON file"
    )
    parser.add_argument(
        "--compare",
        nargs=2,
        metavar=("LOCAL_JSON", "VPS_JSON"),
        help="Compare two saved benchmark results",
    )

    args = parser.parse_args()

    if args.compare:
        compare_results(args.compare[0], args.compare[1])
        return 0

    result = await benchmark_exchange(args.exchange, args.runs)
    print_results(result)

    result_dict = asdict(result)

    if args.output:
        with open(args.output, "w") as f:
            json.dump(result_dict, f, indent=2)
        print(f"  Results saved to {args.output}")

    if args.json:
        print(json.dumps(result_dict, indent=2))

    return 0


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))
