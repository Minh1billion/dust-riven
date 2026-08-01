# Dust Riven

![Rust](https://img.shields.io/badge/rust-stable-orange?logo=rust)
![PyO3](https://img.shields.io/badge/PyO3-extension-blue)
![Python](https://img.shields.io/badge/python-3.8%2B-blue?logo=python)
![License](https://img.shields.io/badge/license-MIT-green)

Dust Riven is a small Rust extension for Python, built with [PyO3](https://pyo3.rs/). It provides a `Signal` class, a simple event system similar to observer/pub-sub patterns. You create a `Signal`, connect callbacks to it, and `emit` it with arguments to call all connected callbacks.

## What it does

`Signal` is a thread-safe event emitter. It lets you register functions that run when the signal is emitted, and it supports:

- normal connections
- one-time connections
- connections that expire after a fixed number of calls
- weak references, so a callback can be garbage collected without needing to manually disconnect it

## Basic usage

```python
import dust_riven

signal = dust_riven.Signal("on_update")
```

`name` is optional and defaults to `None` - `dust_riven.Signal()` works just as well as `dust_riven.Signal("on_update")`. Naming a signal is mainly useful for `repr(signal)`, which is handy in logs and debuggers when a program has many signals.

- `Signal(name=None)` - creates a new signal, optionally with a name
- `connect(callback, weak=False)` - registers a callback, returns an id used to disconnect it later
- `connect_once(callback, weak=False)` - callback runs on the first emit only
- `connect_finite(callback, times, weak=False)` - callback runs for a fixed number of emits, then is removed
- `disconnect(id)` - removes a specific callback
- `emit(*args, on_error="fast_fail", **kwargs)` - calls all connected callbacks with the given arguments. With `on_error="fast_fail"` (default), the first exception raised stops execution and propagates immediately, and remaining callbacks are not called. With `on_error="collect"`, every callback runs regardless of exceptions; the returned list contains each callback's return value, or the exception instance itself in place of a return value for any callback that raised.
- `emit_async(*args, **kwargs)` - like `emit`, but if a callback returns an awaitable (e.g. it's an `async def`), those are collected and run concurrently with `asyncio.gather`; must be awaited
- `len(signal)` - number of callbacks currently connected

Pass `weak=True` on any connect method to hold a weak reference instead of a strong one, so the callback can be garbage collected normally if nothing else references it. If the callback has no other strong reference at the time you connect it (so it would be garbage collected immediately), the connect call raises `TypeError` instead of silently connecting a listener that can never fire.

## Examples

### Connect and emit

```python
import dust_riven

signal = dust_riven.Signal("on_update")

def handler(message):
    print("got:", message)

signal.connect(handler)
signal.emit("hello world")
```

### Connect once

```python
def setup_handler():
    print("setup ran")

signal.connect_once(setup_handler)
signal.emit()  # prints "setup ran"
signal.emit()  # does nothing, handler already removed
```

### Connect finite

```python
def limited_handler():
    print("called")

signal.connect_finite(limited_handler, 3)
signal.emit()  # called
signal.emit()  # called
signal.emit()  # called
signal.emit()  # nothing happens, removed after 3 calls
```

### Collecting errors instead of failing fast

```python
def ok():
    return "fine"

def boom():
    raise ValueError("bad listener")

signal.connect(ok)
signal.connect(boom)

results = signal.emit(on_error="collect")
# results == ["fine", ValueError("bad listener")]
```

### Async emit

```python
import asyncio
import dust_riven

signal = dust_riven.Signal("on_update")

def sync_handler(value):
    print("sync:", value)

async def async_handler(value):
    await asyncio.sleep(0.1)
    print("async:", value)

signal.connect(sync_handler)
signal.connect(async_handler)

async def main():
    # sync_handler runs immediately; async_handler is awaited
    # concurrently alongside any other async listeners
    await signal.emit_async(42)

asyncio.run(main())
```

### Weak connection

```python
class Listener:
    def handle(self, value):
        print("received", value)

listener = Listener()
signal.connect(listener.handle, weak=True)

del listener
signal.emit(42)  # dead reference is dropped silently, no crash
```

### Disconnect

```python
cb_id = signal.connect(handler)
signal.disconnect(cb_id)
```

### Listener count

```python
print(len(signal))
```

## Behavior notes

- Callbacks are collected into a snapshot before being called, so connecting or disconnecting callbacks from inside another callback during `emit` is safe.
- If a weakly referenced callback has already been garbage collected, it is silently removed the next time `emit` runs.
- Callbacks connected with `connect_once` or `connect_finite` are automatically removed once they've been called the requested number of times.
- By default, `emit` uses `on_error="fast_fail"`: the first exception raised by a callback propagates immediately and any callbacks after it are skipped. With `on_error="collect"`, all callbacks run no matter what, and exceptions are returned in the result list rather than raised.
- `emit_async` calls every callback the same way `emit` does; any callback that returns an awaitable (e.g. an `async def`) has that awaitable scheduled via `asyncio.gather` and run concurrently once you `await` the result. Purely synchronous callbacks run immediately, before the returned value is awaited.
- `emit_async` must be called from a thread with an already-running `asyncio` event loop (i.e. `await signal.emit_async()` from inside a coroutine) - this applies even if every connected callback is synchronous. Calling it with no loop running (e.g. `asyncio.run(signal.emit_async())`, where the call happens before `run` starts its loop) raises `RuntimeError`.
- With `emit_async`, an exception from a synchronous callback is raised as soon as it's called (before you even reach the `await`), while an exception from an async callback surfaces when the gathered result is awaited.
- If a callback raises during `emit_async`, remaining callbacks are not called, and any async callback's coroutine already created before the error is closed rather than left dangling.
- `Signal` participates in Python's cyclic garbage collector, so a callback that holds a reference back to its own `Signal` (e.g. a closure or bound method capturing the signal it's connected to) doesn't leak - `gc.collect()` can still find and break that cycle even though nothing was ever explicitly disconnected.

## Building

This project uses PyO3 and is built as a native Python extension, typically with [maturin](https://www.maturin.rs/). Once built, it exposes a Python module named `dust_riven` containing the `Signal` class.

### Requirements

- Rust toolchain
- Python with a PyO3-compatible version
- `parking_lot`, `once_cell`, and `smallvec` crates

## Running the benchmark against blinker

The repository includes `bench.py`, a script that compares `dust_riven` against the [blinker](https://pypi.org/project/blinker/) library for `connect` and `emit` performance, across different listener counts, emit counts, and strong vs weak callback variants.

**1. Create and activate a virtual environment**

```bash
python -m venv .venv
source .venv/bin/activate
```

On Windows, activate with `.venv\Scripts\activate` instead.

**2. Install the needed Python packages**

```bash
pip install blinker tqdm maturin
```

**3. Build and install dust_riven into the same venv**

```bash
maturin develop --release
```

Run this from the project root (the folder containing `Cargo.toml` and `pyproject.toml`). It compiles the Rust code and installs the `dust_riven` module directly into the active venv.

**4. Run the benchmark**

```bash
python bench.py
```

This runs the full matrix of listener counts and emit counts for both strong and weak variants, and prints comparison tables with minimum/median timings plus a speedup ratio.

For a fast smoke test instead of the full matrix:

```bash
python bench.py --quick
```

You can also narrow the run with options, for example:

```bash
python bench.py --listeners 1,100,1000 --emits 100,1000 --repeats 5 --variants strong --measure emit
```

Available options: `--listeners`, `--emits`, `--repeats`, `--variants`, `--libraries`, `--measure`. Run `python bench.py --help` for the full list with descriptions.

## License

MIT - see [LICENSE](LICENSE) for details.