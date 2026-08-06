import asyncio
import faulthandler
import gc
import os
import sys
import threading

import pytest
import dust_riven

faulthandler.enable()

H1_ITERS = int(os.environ.get("DUST_RIVEN_PRESSURE_ITERS", 200))
WATCHDOG_TIMEOUT = float(os.environ.get("DUST_RIVEN_PRESSURE_TIMEOUT", 5.0))
H3_TIMEOUT = float(os.environ.get("DUST_RIVEN_PRESSURE_H3_TIMEOUT", 10.0))
H3_THREADS = int(os.environ.get("DUST_RIVEN_PRESSURE_H3_THREADS", 64))


class Watchdog:
    def __init__(self, timeout, label=""):
        self.timeout = timeout
        self.label = label
        self._done = threading.Event()
        self._thread = None

    def _watch(self):
        if not self._done.wait(self.timeout):
            print(f"\n!!! [{self.label}] HUNG FOR MORE THAN {self.timeout}s -> "
                  f"SUSPECTED DEADLOCK !!!", file=sys.stderr)
            faulthandler.dump_traceback(file=sys.stderr, all_threads=True)
            sys.stderr.flush()
            os._exit(1)

    def __enter__(self):
        self._thread = threading.Thread(target=self._watch, daemon=True)
        self._thread.start()
        return self

    def __exit__(self, *exc):
        self._done.set()
        return False


def _is_free_threaded():
    getter = getattr(sys, "_is_gil_enabled", None)
    if getter is None:
        return False
    return not getter()


def _h1_one_iteration(timeout):
    sig = dust_riven.Signal("h1")
    wid_holder = {}

    class Victim:
        pass

    def victim_cb(*a, **kw):
        pass

    victim = Victim()
    victim.cb = victim_cb
    wid_holder["wid"] = sig.connect(victim.cb, weak=True)

    reentry_ran = threading.Event()

    class Reentrant:
        def __del__(self):
            reentry_ran.set()
            try:
                sig.disconnect(wid_holder["wid"])
                sig.connect(lambda *a, **kw: None)
            except Exception:
                pass

    async def run():
        await sig.emit_async()

    with Watchdog(timeout, label="H1"):
        r_holder = [Reentrant()]
        del victim
        r_holder.clear()
        gc.collect()
        asyncio.run(run())

    return reentry_ran.is_set()


def test_h1_gc_finalizer_reentrancy_does_not_deadlock_emit_async():
    gc.set_threshold(1, 1, 1)
    any_reentry = False
    try:
        for _ in range(H1_ITERS):
            fired = _h1_one_iteration(WATCHDOG_TIMEOUT)
            any_reentry = any_reentry or fired
    finally:
        gc.set_threshold(700, 10, 10)

    if not any_reentry:
        pytest.skip("finalizer never fired at the right moment; increase "
                     "DUST_RIVEN_PRESSURE_ITERS to raise confidence")


def test_h2_callback_exception_mid_emit_async_does_not_orphan_coroutine():
    sig = dust_riven.Signal("h2")
    ran = []

    async def good_cb():
        ran.append("good_cb")
        await asyncio.sleep(0)

    def bad_cb():
        raise RuntimeError("boom")

    async def good_cb_2():
        ran.append("good_cb_2")
        await asyncio.sleep(0)

    sig.connect(good_cb)
    sig.connect(bad_cb)
    sig.connect(good_cb_2)

    async def run():
        await sig.emit_async()

    with Watchdog(WATCHDOG_TIMEOUT, label="H2"):
        with pytest.raises(RuntimeError):
            asyncio.run(run())
        gc.collect()

    assert ran == []


@pytest.mark.skipif(not _is_free_threaded(),
                     reason="requires CPython free-threaded build "
                            "(Py_GIL_DISABLED), e.g. `uv python install 3.13t`")
def test_h3_connect_once_is_exactly_once_under_real_concurrency():
    sig = dust_riven.Signal("h3")
    counter = {"n": 0}
    lock = threading.Lock()

    def cb():
        with lock:
            counter["n"] += 1

    sig.connect_once(cb)
    barrier = threading.Barrier(H3_THREADS)

    def worker():
        barrier.wait()
        try:
            sig.emit()
        except Exception:
            pass

    with Watchdog(H3_TIMEOUT, label="H3"):
        threads = [threading.Thread(target=worker) for _ in range(H3_THREADS)]
        for t in threads:
            t.start()
        for t in threads:
            t.join()

    assert counter["n"] == 1


def test_h4a_emit_async_raises_when_awaited_without_running_loop():
    sig = dust_riven.Signal("h4a")
    sig.connect(lambda: None)

    with pytest.raises((ValueError, RuntimeError)):
        asyncio.run(sig.emit_async())


def test_h4b_emit_async_cross_loop_behavior():
    sig = dust_riven.Signal("h4b")
    sig.connect(lambda: None)

    result_holder = {}

    def worker_thread():
        loop = asyncio.new_event_loop()
        asyncio.set_event_loop(loop)
        try:
            async def inner():
                return sig.emit_async()
            result_holder["future"] = loop.run_until_complete(inner())
        finally:
            loop.close()

    with Watchdog(WATCHDOG_TIMEOUT, label="H4b"):
        t = threading.Thread(target=worker_thread)
        t.start()
        t.join()

        fut = result_holder.get("future")
        assert fut is not None

        async def await_elsewhere():
            await fut

        try:
            asyncio.run(await_elsewhere())
        except Exception:
            pass