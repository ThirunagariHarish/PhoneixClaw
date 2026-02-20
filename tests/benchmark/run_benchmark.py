"""Latency benchmark harness for the trade pipeline.

Run: python3 -m tests.benchmark.run_benchmark --count 100
"""
import argparse
import statistics
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from services.trade_executor.src.buffer import calculate_buffered_price
from services.trade_parser.src.parser import parse_trade_message

SAMPLE_MESSAGES = [
    "Bought SPX 6940C at 4.80",
    "Sold 50% SPX 6950C at 6.50",
    "Bought IWM 250P at 1.50 Exp: 02/20/2026",
    "Bought 5 AAPL 190C at 3.50",
    "Sold 70% TSLA 250C at 8.00",
]


def benchmark_parse(count: int) -> list[float]:
    latencies = []
    for i in range(count):
        msg = SAMPLE_MESSAGES[i % len(SAMPLE_MESSAGES)]
        start = time.perf_counter_ns()
        parse_trade_message(msg)
        elapsed_ns = time.perf_counter_ns() - start
        latencies.append(elapsed_ns / 1_000_000)
    return latencies


def benchmark_buffer(count: int) -> list[float]:
    latencies = []
    for i in range(count):
        start = time.perf_counter_ns()
        calculate_buffered_price(4.80 + i * 0.01, "BUY", "SPX")
        elapsed_ns = time.perf_counter_ns() - start
        latencies.append(elapsed_ns / 1_000_000)
    return latencies


def report(name: str, latencies: list[float]):
    latencies.sort()
    p50 = latencies[len(latencies) // 2]
    p95 = latencies[int(len(latencies) * 0.95)]
    p99 = latencies[int(len(latencies) * 0.99)]
    print(f"\n{name} ({len(latencies)} iterations):")
    print(f"  p50: {p50:.3f}ms  p95: {p95:.3f}ms  p99: {p99:.3f}ms  mean: {statistics.mean(latencies):.3f}ms")


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--count", type=int, default=1000)
    args = parser.parse_args()

    parse_lat = benchmark_parse(args.count)
    buffer_lat = benchmark_buffer(args.count)
    report("Trade Parser", parse_lat)
    report("Buffer Pricing", buffer_lat)
    p95_parse = sorted(parse_lat)[int(len(parse_lat) * 0.95)]
    p95_buffer = sorted(buffer_lat)[int(len(buffer_lat) * 0.95)]
    print(f"\nTotal parse+buffer p95: {p95_parse + p95_buffer:.3f}ms")
