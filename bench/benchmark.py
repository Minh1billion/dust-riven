"""Usage: python bench/benchmark.py --repeats 5 --csv results.csv"""

import argparse
import csv
import statistics
import sys
import time
from dataclasses import dataclass, field
from typing import Callable, List

from dust_riven import Signal as RustSignal
from blinker import Signal as BlinkerSignal


@dataclass
class TimingResult:
    label: str
    samples: List[float] = field(default_factory=list)

    def add(self, value: float) -> None:
        self.samples.append(value)

    @property
    def mean(self) -> float:
        return statistics.mean(self.samples)

    @property
    def median(self) -> float:
        return statistics.median(self.samples)

    @property
    def stdev(self) -> float:
        return statistics.stdev(self.samples) if len(self.samples) > 1 else 0.0

    @property
    def best(self) -> float:
        return min(self.samples)

    @property
    def worst(self) -> float:
        return max(self.samples)


@dataclass
class ScenarioResult:
    name: str
    n_listeners: int
    n_emits: int
    rust_connect: TimingResult
    rust_emit: TimingResult
    rust_disconnect: TimingResult
    blinker_connect: TimingResult
    blinker_emit: TimingResult
    blinker_disconnect: TimingResult


def time_call(fn: Callable[[], None]) -> float:
    start = time.perf_counter()
    fn()
    return time.perf_counter() - start


def bench_rust_connect(n: int) -> tuple:
    signal = RustSignal()
    listeners = [(lambda *a: None) for _ in range(n)]
    handles = []

    def run():
        for listener in listeners:
            handles.append(signal.connect(listener))

    elapsed = time_call(run)
    return elapsed, signal, handles


def bench_rust_disconnect(signal, handles: List[int]) -> float:
    def run():
        for handle in handles:
            signal.disconnect(handle)

    return time_call(run)


def bench_rust_emit(signal, n_emits: int) -> float:
    def run():
        for _ in range(n_emits):
            signal.emit(1, 2, 3)

    return time_call(run)


def bench_blinker_connect(n: int) -> tuple:
    signal = BlinkerSignal()
    listeners = [(lambda sender, **kw: None) for _ in range(n)]

    def run():
        for listener in listeners:
            signal.connect(listener, weak=False)

    elapsed = time_call(run)
    return elapsed, signal, listeners


def bench_blinker_disconnect(signal, listeners: List[Callable]) -> float:
    def run():
        for listener in listeners:
            signal.disconnect(listener)

    return time_call(run)


def bench_blinker_emit(signal, n_emits: int) -> float:
    def run():
        for _ in range(n_emits):
            signal.send(None, a=1, b=2, c=3)

    return time_call(run)


def run_scenario(name: str, n_listeners: int, n_emits: int, repeats: int) -> ScenarioResult:
    rust_connect = TimingResult("rust_connect")
    rust_emit = TimingResult("rust_emit")
    rust_disconnect = TimingResult("rust_disconnect")
    blinker_connect = TimingResult("blinker_connect")
    blinker_emit = TimingResult("blinker_emit")
    blinker_disconnect = TimingResult("blinker_disconnect")

    for _ in range(repeats):
        elapsed, signal, handles = bench_rust_connect(n_listeners)
        rust_connect.add(elapsed)
        rust_emit.add(bench_rust_emit(signal, n_emits))
        rust_disconnect.add(bench_rust_disconnect(signal, handles))

        elapsed, signal, listeners = bench_blinker_connect(n_listeners)
        blinker_connect.add(elapsed)
        blinker_emit.add(bench_blinker_emit(signal, n_emits))
        blinker_disconnect.add(bench_blinker_disconnect(signal, listeners))

    return ScenarioResult(
        name=name,
        n_listeners=n_listeners,
        n_emits=n_emits,
        rust_connect=rust_connect,
        rust_emit=rust_emit,
        rust_disconnect=rust_disconnect,
        blinker_connect=blinker_connect,
        blinker_emit=blinker_emit,
        blinker_disconnect=blinker_disconnect,
    )


def format_seconds(value: float) -> str:
    return f"{value:.5f}s"


def format_speedup(rust_value: float, blinker_value: float) -> str:
    if rust_value <= 0:
        return "n/a"
    return f"{blinker_value / rust_value:.1f}x"


def print_scenario(result: ScenarioResult) -> None:
    print(f"\nScenario: {result.name}")
    print(f"listeners={result.n_listeners:,} emits={result.n_emits:,}")
    print(f"{'operation':<12}{'engine':<10}{'mean':<12}{'median':<12}{'stdev':<12}{'speedup':<10}")

    rows = [
        ("connect", result.rust_connect, result.blinker_connect),
        ("emit", result.rust_emit, result.blinker_emit),
        ("disconnect", result.rust_disconnect, result.blinker_disconnect),
    ]

    for op_name, rust_result, blinker_result in rows:
        speedup = format_speedup(rust_result.mean, blinker_result.mean)
        print(f"{op_name:<12}{'rust':<10}{format_seconds(rust_result.mean):<12}"
              f"{format_seconds(rust_result.median):<12}{format_seconds(rust_result.stdev):<12}{speedup:<10}")
        print(f"{'':<12}{'blinker':<10}{format_seconds(blinker_result.mean):<12}"
              f"{format_seconds(blinker_result.median):<12}{format_seconds(blinker_result.stdev):<12}{'':<10}")


def write_csv(results: List[ScenarioResult], path: str) -> None:
    with open(path, "w", newline="") as handle:
        writer = csv.writer(handle)
        writer.writerow([
            "scenario", "n_listeners", "n_emits", "operation", "engine",
            "mean_s", "median_s", "stdev_s", "best_s", "worst_s",
        ])
        for result in results:
            pairs = [
                ("connect", "rust", result.rust_connect),
                ("connect", "blinker", result.blinker_connect),
                ("emit", "rust", result.rust_emit),
                ("emit", "blinker", result.blinker_emit),
                ("disconnect", "rust", result.rust_disconnect),
                ("disconnect", "blinker", result.blinker_disconnect),
            ]
            for op_name, engine, timing in pairs:
                writer.writerow([
                    result.name, result.n_listeners, result.n_emits, op_name, engine,
                    f"{timing.mean:.6f}", f"{timing.median:.6f}", f"{timing.stdev:.6f}",
                    f"{timing.best:.6f}", f"{timing.worst:.6f}",
                ])


def default_scenarios() -> List[tuple]:
    return [
        ("small", 100, 1_000),
        ("medium", 1_000, 1_000),
        ("large", 10_000, 100),
        ("very_large", 100_000, 10),
    ]


def parse_args(argv: List[str]) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Benchmark dust_riven Signal against blinker Signal")
    parser.add_argument("--repeats", type=int, default=3, help="number of repeats per scenario")
    parser.add_argument("--csv", type=str, default=None, help="optional path to write results as CSV")
    return parser.parse_args(argv)


def main(argv: List[str]) -> int:
    args = parse_args(argv)
    scenarios = default_scenarios()
    results = []

    for name, n_listeners, n_emits in scenarios:
        result = run_scenario(name, n_listeners, n_emits, args.repeats)
        results.append(result)
        print_scenario(result)

    if args.csv:
        write_csv(results, args.csv)
        print(f"\nResults written to {args.csv}")

    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))