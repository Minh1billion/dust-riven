# dust-riven

A fast, thread-safe Signal (observer/pub-sub) primitive for Python, implemented in Rust with PyO3 (https://pyo3.rs/).

Inspired by blinker (https://github.com/pallets-eco/blinker), dust-riven aims to be a drop-in-style, lightweight alternative with significantly faster connect/emit performance.

## Install

```bash
pip install dust-riven
```

## Usage

```python
from dust_riven import Signal

signal = Signal()

def on_event(*args):
    print("received:", args)

handle = signal.connect(on_event)
signal.emit(1, 2, 3)
# prints: received: (1, 2, 3)

signal.disconnect(handle)
```

### One-time listeners

Use once() to register a listener that automatically disconnects itself after it runs a single time.

```python
signal = Signal()
signal.once(lambda: print("only runs once"))

signal.emit()
signal.emit()
# prints "only runs once" a single time
```

### Async listeners

Sync listeners are called with emit(). Async listeners must be called with emit_async(), which awaits all coroutine listeners concurrently.

```python
import asyncio
from dust_riven import Signal

signal = Signal()

async def on_event(x):
    await asyncio.sleep(0.1)
    print("handled:", x)

signal.connect(on_event)

async def main():
    await signal.emit_async(42)

asyncio.run(main())
```

Calling emit() with an async listener registered raises a TypeError explaining that emit_async() should be used instead.

### Error handling strategy

Both emit() and emit_async() accept an on_error keyword argument:

- on_error="collect" (default): every listener runs, then the first error encountered is raised.
- on_error="fail_fast": stops immediately at the first error, remaining listeners are not called.

```python
signal.emit(1, 2, on_error="fail_fast")
await signal.emit_async(1, 2, on_error="collect")
```

## API

- Signal() - create a new signal.
- signal.connect(callback) -> int - register a callback, returns a handle.
- signal.once(callback) -> int - register a callback that auto-disconnects after it runs once, returns a handle.
- signal.disconnect(handle) - remove a previously connected callback.
- signal.emit(*args, on_error="collect") - call all connected sync listeners with *args.
- signal.emit_async(*args, on_error="collect") - await all connected listeners (sync and async) with *args, running coroutines concurrently.

## Benchmark

A comparison script against blinker is available in bench/benchmark.py:

```bash
pip install blinker
python bench/benchmark.py
```

## Development

Built with maturin (https://www.maturin.rs/):

```bash
maturin develop
```

Run tests:

```bash
pip install -e ".[dev]"
pytest
```

## License

MIT