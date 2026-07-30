import argparse
import gc
import itertools
import statistics
import time
from dataclasses import dataclass
from typing import Optional

from tqdm import tqdm

import blinker
import dust_riven


def make_unique_callback():
    def cb(*args, **kwargs):
        pass
    return cb


LIBRARIES = {
    "blinker": {
        "new_signal": lambda: blinker.Signal(),
        "connect": lambda sig, cb, weak: sig.connect(cb, weak=weak),
        "emit": lambda sig: sig.send(),
    },
    "dust_riven": {
        "new_signal": lambda: dust_riven.Signal("bench"),
        "connect": lambda sig, cb, weak: sig.connect(cb, weak=weak),
        "emit": lambda sig: sig.emit(),
    },
}

VARIANTS = {"strong": False, "weak": True}


@dataclass
class BenchConfig:
    listeners: list
    emits: list
    repeats: int
    variants: list
    libraries: list
    measure: list


@dataclass
class CaseResult:
    library: str
    variant: str
    kind: str
    n_listeners: int
    n_emits: Optional[int]
    t_min: float
    t_med: float


def _build_signal(lib_name, n_listeners, weak):
    new_signal = LIBRARIES[lib_name]["new_signal"]
    connect = LIBRARIES[lib_name]["connect"]
    sig = new_signal()
    callbacks = [make_unique_callback() for _ in range(n_listeners)]
    for cb in callbacks:
        connect(sig, cb, weak)
    return sig, callbacks


def time_connect(lib_name, weak, n_listeners, repeats, progress=None):
    new_signal = LIBRARIES[lib_name]["new_signal"]
    connect = LIBRARIES[lib_name]["connect"]
    samples = []
    for i in range(repeats + 1):
        callbacks = [make_unique_callback() for _ in range(n_listeners)]
        sig = new_signal()
        gc.collect()
        gc.disable()
        start = time.perf_counter()
        for cb in callbacks:
            connect(sig, cb, weak)
        end = time.perf_counter()
        gc.enable()
        if i > 0:
            samples.append(end - start)
        if progress is not None:
            progress.update(1)
    return samples


def time_emit(lib_name, weak, n_listeners, n_emits, repeats, progress=None):
    emit = LIBRARIES[lib_name]["emit"]
    samples = []
    for i in range(repeats + 1):
        sig, callbacks = _build_signal(lib_name, n_listeners, weak)
        gc.collect()
        gc.disable()
        start = time.perf_counter()
        for _ in range(n_emits):
            emit(sig)
        end = time.perf_counter()
        gc.enable()
        if i > 0:
            samples.append(end - start)
        if progress is not None:
            progress.update(1)
    return samples


def build_cases(cfg: BenchConfig):
    cases = []
    if "connect" in cfg.measure:
        for variant, lib, n_listeners in itertools.product(cfg.variants, cfg.libraries, cfg.listeners):
            cases.append(("connect", lib, variant, n_listeners, None))
    if "emit" in cfg.measure:
        for variant, lib, n_listeners, n_emits in itertools.product(cfg.variants, cfg.libraries, cfg.listeners, cfg.emits):
            cases.append(("emit", lib, variant, n_listeners, n_emits))
    return cases


def run_cases(cfg: BenchConfig) -> list:
    cases = build_cases(cfg)
    results = []
    outer = tqdm(cases, desc="benchmarking", unit="case", position=0)
    for kind, lib, variant, n_listeners, n_emits in outer:
        outer.set_postfix(kind=kind, lib=lib, variant=variant, L=n_listeners, E=n_emits or "-")
        weak = VARIANTS[variant]
        label = f"{kind}:{lib}:{variant}:L{n_listeners}" + (f":E{n_emits}" if n_emits else "")
        inner = tqdm(total=cfg.repeats + 1, desc=label, unit="run", position=1, leave=False)
        try:
            if kind == "connect":
                samples = time_connect(lib, weak, n_listeners, cfg.repeats, progress=inner)
            else:
                samples = time_emit(lib, weak, n_listeners, n_emits, cfg.repeats, progress=inner)
        finally:
            inner.close()
        results.append(CaseResult(
            library=lib, variant=variant, kind=kind,
            n_listeners=n_listeners, n_emits=n_emits,
            t_min=min(samples), t_med=statistics.median(samples),
        ))
    outer.close()
    return results


def fmt(t):
    if t < 1e-3:
        return f"{t*1e6:.2f}us"
    if t < 1:
        return f"{t*1e3:.3f}ms"
    return f"{t:.3f}s"


def print_table(results, kind, variant, libraries):
    rows = [r for r in results if r.kind == kind and r.variant == variant]
    if not rows:
        return
    key_fields = ("n_listeners",) if kind == "connect" else ("n_listeners", "n_emits")
    keys = sorted({tuple(getattr(r, f) for f in key_fields) for r in rows})
    by_key_lib = {(tuple(getattr(r, f) for f in key_fields), r.library): r for r in rows}

    title = "connect() cost, N listeners" if kind == "connect" else "emit() cost, listeners x emits"
    print(f"\n=== {title} [{variant}] ===")

    key_header = "listeners" if kind == "connect" else "listeners     emits"
    col_header = " | ".join(f"{lib+' min':>14} {lib+' med':>14}" for lib in libraries)
    extra = " | speedup(med)" if len(libraries) == 2 else ""
    print(f"{key_header:>18} | {col_header}{extra}")

    for key in keys:
        key_str = " ".join(f"{v:>8}" for v in key)
        cells = []
        for lib in libraries:
            res = by_key_lib.get((key, lib))
            cells.append(f"{fmt(res.t_min):>14} {fmt(res.t_med):>14}" if res else f"{'n/a':>14} {'n/a':>14}")
        line = f"{key_str:>18} | " + " | ".join(cells)
        if len(libraries) == 2:
            a = by_key_lib.get((key, libraries[0]))
            b = by_key_lib.get((key, libraries[1]))
            if a and b and b.t_med > 0:
                line += f" | {a.t_med / b.t_med:>11.2f}x"
        print(line)


def print_results(results, cfg: BenchConfig):
    for variant in cfg.variants:
        for kind in cfg.measure:
            print_table(results, kind, variant, cfg.libraries)


def parse_int_list(s):
    return [int(x) for x in s.split(",") if x.strip()]


def parse_config() -> BenchConfig:
    parser = argparse.ArgumentParser(description="Benchmark blinker vs dust_riven Signal implementations.")
    parser.add_argument("--listeners", type=parse_int_list, default=[1, 10, 100, 1000, 3000],
                         help="Comma-separated listener counts, e.g. 1,10,100")
    parser.add_argument("--emits", type=parse_int_list, default=[1, 10, 100, 1000, 3000],
                         help="Comma-separated emit counts, e.g. 1,10,100")
    parser.add_argument("--repeats", type=int, default=7, help="Samples per case")
    parser.add_argument("--variants", type=lambda s: s.split(","), default=["strong", "weak"],
                         help="Comma-separated subset of: strong,weak")
    parser.add_argument("--libraries", type=lambda s: s.split(","), default=["blinker", "dust_riven"],
                         help="Comma-separated subset of: blinker,dust_riven")
    parser.add_argument("--measure", type=lambda s: s.split(","), default=["connect", "emit"],
                         help="Comma-separated subset of: connect,emit")
    parser.add_argument("--quick", action="store_true",
                         help="Shortcut for a small smoke-test matrix (overrides listeners/emits/repeats)")
    args = parser.parse_args()

    for v in args.variants:
        if v not in VARIANTS:
            parser.error(f"unknown variant '{v}', choose from {list(VARIANTS)}")
    for lib in args.libraries:
        if lib not in LIBRARIES:
            parser.error(f"unknown library '{lib}', choose from {list(LIBRARIES)}")
    for m in args.measure:
        if m not in ("connect", "emit"):
            parser.error(f"unknown measure '{m}', choose from connect,emit")

    if args.quick:
        return BenchConfig(
            listeners=[1, 100], emits=[1, 100], repeats=3,
            variants=args.variants, libraries=args.libraries, measure=args.measure,
        )

    return BenchConfig(
        listeners=args.listeners, emits=args.emits, repeats=args.repeats,
        variants=args.variants, libraries=args.libraries, measure=args.measure,
    )


def main():
    cfg = parse_config()
    results = run_cases(cfg)
    print_results(results, cfg)


if __name__ == "__main__":
    main()