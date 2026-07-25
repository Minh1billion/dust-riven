# dust-riven

A fast, thread-safe `Signal` (observer/pub-sub) primitive for Python, implemented in Rust with [PyO3](https://pyo3.rs/).

Inspired by [blinker](https://github.com/pallets-eco/blinker), `dust-riven` aims to be a drop-in-style, lightweight alternative with significantly faster `connect`/`emit` performance.

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
signal.emit(1, 2, 3)  # -> received: (1, 2, 3)

signal.disconnect(handle)
```

## API

- `Signal()` - create a new signal.
- `signal.connect(callback) -> int` - register a callback, returns a handle.
- `signal.disconnect(handle)` - remove a previously connected callback.
- `signal.emit(*args)` - call all connected listeners with `*args`.

## Benchmark

A comparison script against `blinker` is available in [`bench/benchmark.py`](bench/benchmark.py):

```bash
pip install blinker
python bench/benchmark.py
```

## Development

Built with [maturin](https://www.maturin.rs/):

```bash
maturin develop
```

## License

MIT