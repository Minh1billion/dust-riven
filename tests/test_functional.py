import asyncio

import pytest
import dust_riven


def test_new_signal_has_name_in_repr():
    sig = dust_riven.Signal("clicked")
    assert "clicked" in repr(sig)


def test_new_signal_has_zero_listeners():
    sig = dust_riven.Signal("clicked")
    assert len(sig) == 0


def test_connect_returns_unique_ids():
    sig = dust_riven.Signal("s")
    id1 = sig.connect(lambda: None)
    id2 = sig.connect(lambda: None)
    assert id1 != id2


def test_connect_increments_length():
    sig = dust_riven.Signal("s")
    sig.connect(lambda: None)
    sig.connect(lambda: None)
    assert len(sig) == 2


def test_connect_rejects_non_callable():
    sig = dust_riven.Signal("s")
    with pytest.raises(TypeError):
        sig.connect(42)


def test_connect_rejects_none():
    sig = dust_riven.Signal("s")
    with pytest.raises(TypeError):
        sig.connect(None)


def test_connect_accepts_lambda():
    sig = dust_riven.Signal("s")
    sig.connect(lambda *a, **kw: None)
    assert len(sig) == 1


def test_connect_accepts_function():
    sig = dust_riven.Signal("s")
    def cb():
        pass
    sig.connect(cb)
    assert len(sig) == 1


def test_connect_accepts_bound_method():
    class Handler:
        def on_event(self):
            pass
    sig = dust_riven.Signal("s")
    sig.connect(Handler().on_event)
    assert len(sig) == 1


def test_connect_accepts_callable_object():
    class Handler:
        def __call__(self):
            pass
    sig = dust_riven.Signal("s")
    sig.connect(Handler())
    assert len(sig) == 1


def test_disconnect_removes_listener():
    sig = dust_riven.Signal("s")
    cid = sig.connect(lambda: None)
    sig.disconnect(cid)
    assert len(sig) == 0


def test_disconnect_returns_true_when_found():
    sig = dust_riven.Signal("s")
    cid = sig.connect(lambda: None)
    assert sig.disconnect(cid) is True


def test_disconnect_returns_false_when_missing():
    sig = dust_riven.Signal("s")
    assert sig.disconnect(999) is False


def test_disconnect_twice_returns_false_second_time():
    sig = dust_riven.Signal("s")
    cid = sig.connect(lambda: None)
    sig.disconnect(cid)
    assert sig.disconnect(cid) is False


def test_disconnect_only_removes_target_listener():
    sig = dust_riven.Signal("s")
    id1 = sig.connect(lambda: None)
    id2 = sig.connect(lambda: None)
    sig.disconnect(id1)
    assert len(sig) == 1
    assert sig.disconnect(id2) is True


def test_emit_calls_all_listeners():
    calls = []
    sig = dust_riven.Signal("s")
    sig.connect(lambda: calls.append(1))
    sig.connect(lambda: calls.append(2))
    sig.connect(lambda: calls.append(3))
    sig.emit()
    assert sorted(calls) == [1, 2, 3]


def test_emit_with_no_listeners_does_nothing():
    sig = dust_riven.Signal("s")
    sig.emit()


def test_emit_passes_positional_args():
    received = []
    sig = dust_riven.Signal("s")
    sig.connect(lambda a, b: received.append((a, b)))
    sig.emit(1, 2)
    assert received == [(1, 2)]


def test_emit_passes_keyword_args():
    received = []
    sig = dust_riven.Signal("s")
    sig.connect(lambda **kw: received.append(kw))
    sig.emit(x=1, y=2)
    assert received == [{"x": 1, "y": 2}]


def test_emit_passes_mixed_args():
    received = []
    sig = dust_riven.Signal("s")
    sig.connect(lambda a, *, b: received.append((a, b)))
    sig.emit(1, b=2)
    assert received == [(1, 2)]


def test_emit_calls_listeners_multiple_times_correctly():
    counter = {"n": 0}
    sig = dust_riven.Signal("s")
    sig.connect(lambda: counter.__setitem__("n", counter["n"] + 1))
    sig.emit()
    sig.emit()
    sig.emit()
    assert counter["n"] == 3


def test_emit_propagates_exception_from_callback():
    sig = dust_riven.Signal("s")
    def bad():
        raise ValueError("boom")
    sig.connect(bad)
    with pytest.raises(ValueError):
        sig.emit()


def test_emit_stops_after_exception():
    calls = []
    sig = dust_riven.Signal("s")
    sig.connect(lambda: calls.append("first"))
    def bad():
        raise RuntimeError("boom")
    sig.connect(bad)
    sig.connect(lambda: calls.append("third"))
    with pytest.raises(RuntimeError):
        sig.emit()
    assert calls == ["first"]


def test_emit_after_disconnect_skips_removed_listener():
    calls = []
    sig = dust_riven.Signal("s")
    cid = sig.connect(lambda: calls.append("a"))
    sig.connect(lambda: calls.append("b"))
    sig.disconnect(cid)
    sig.emit()
    assert calls == ["b"]


def test_disconnect_inside_callback_does_not_crash():
    sig = dust_riven.Signal("s")
    ids = {}
    def self_remove():
        sig.disconnect(ids["self"])
    ids["self"] = sig.connect(self_remove)
    sig.emit()
    assert len(sig) == 0


def test_connect_inside_callback_does_not_crash():
    sig = dust_riven.Signal("s")
    calls = []
    def adder():
        sig.connect(lambda: calls.append("added"))
        calls.append("adder")
    sig.connect(adder)
    sig.emit()
    assert calls == ["adder"]
    sig.emit()
    assert calls == ["adder", "adder", "added"]


def test_repr_reflects_listener_count():
    sig = dust_riven.Signal("s")
    sig.connect(lambda: None)
    sig.connect(lambda: None)
    assert "2" in repr(sig)


def test_len_matches_repr_count():
    sig = dust_riven.Signal("s")
    sig.connect(lambda: None)
    assert len(sig) == 1
    assert "1" in repr(sig)


def test_multiple_signals_are_independent():
    sig1 = dust_riven.Signal("a")
    sig2 = dust_riven.Signal("b")
    calls = []
    sig1.connect(lambda: calls.append("sig1"))
    sig2.connect(lambda: calls.append("sig2"))
    sig1.emit()
    assert calls == ["sig1"]
    sig2.emit()
    assert calls == ["sig1", "sig2"]


def test_large_number_of_listeners_all_called():
    sig = dust_riven.Signal("s")
    counter = {"n": 0}
    for _ in range(5000):
        sig.connect(lambda: counter.__setitem__("n", counter["n"] + 1))
    sig.emit()
    assert counter["n"] == 5000


def test_disconnect_all_then_emit_is_noop():
    sig = dust_riven.Signal("s")
    ids = [sig.connect(lambda: None) for _ in range(10)]
    for cid in ids:
        sig.disconnect(cid)
    assert len(sig) == 0
    sig.emit()


def test_connect_once_returns_id():
    sig = dust_riven.Signal("s")
    cid = sig.connect_once(lambda: None)
    assert isinstance(cid, int)


def test_connect_once_increments_length():
    sig = dust_riven.Signal("s")
    sig.connect_once(lambda: None)
    assert len(sig) == 1


def test_connect_once_rejects_non_callable():
    sig = dust_riven.Signal("s")
    with pytest.raises(TypeError):
        sig.connect_once(42)


def test_connect_once_calls_listener_on_first_emit():
    calls = []
    sig = dust_riven.Signal("s")
    sig.connect_once(lambda: calls.append(1))
    sig.emit()
    assert calls == [1]


def test_connect_once_removed_after_first_emit():
    sig = dust_riven.Signal("s")
    sig.connect_once(lambda: None)
    sig.emit()
    assert len(sig) == 0


def test_connect_once_not_called_on_second_emit():
    calls = []
    sig = dust_riven.Signal("s")
    sig.connect_once(lambda: calls.append(1))
    sig.emit()
    sig.emit()
    assert calls == [1]


def test_connect_once_passes_args():
    received = []
    sig = dust_riven.Signal("s")
    sig.connect_once(lambda a, b: received.append((a, b)))
    sig.emit(1, 2)
    assert received == [(1, 2)]


def test_connect_once_coexists_with_regular_listener():
    calls = []
    sig = dust_riven.Signal("s")
    sig.connect_once(lambda: calls.append("once"))
    sig.connect(lambda: calls.append("regular"))
    sig.emit()
    sig.emit()
    assert calls == ["once", "regular", "regular"]


def test_connect_once_disconnect_before_emit_prevents_call():
    calls = []
    sig = dust_riven.Signal("s")
    cid = sig.connect_once(lambda: calls.append(1))
    sig.disconnect(cid)
    sig.emit()
    assert calls == []


def test_connect_once_accepts_weak():
    sig = dust_riven.Signal("s")
    class Handler:
        def on_event(self):
            pass
    handler = Handler()
    sig.connect_once(handler.on_event, weak=True)
    assert len(sig) == 1


def test_connect_once_rejects_orphan_weak_callback():
    sig = dust_riven.Signal("s")
    class Handler:
        def on_event(self):
            pass
    with pytest.raises(TypeError):
        sig.connect_once(Handler().on_event, weak=True)


def test_connect_finite_returns_id():
    sig = dust_riven.Signal("s")
    cid = sig.connect_finite(lambda: None, 3)
    assert isinstance(cid, int)


def test_connect_finite_rejects_non_callable():
    sig = dust_riven.Signal("s")
    with pytest.raises(TypeError):
        sig.connect_finite(42, 3)


def test_connect_finite_rejects_zero_times():
    sig = dust_riven.Signal("s")
    with pytest.raises(TypeError):
        sig.connect_finite(lambda: None, 0)


def test_connect_finite_called_exact_number_of_times():
    counter = {"n": 0}
    sig = dust_riven.Signal("s")
    sig.connect_finite(lambda: counter.__setitem__("n", counter["n"] + 1), 3)
    for _ in range(5):
        sig.emit()
    assert counter["n"] == 3


def test_connect_finite_removed_after_last_call():
    sig = dust_riven.Signal("s")
    sig.connect_finite(lambda: None, 2)
    sig.emit()
    assert len(sig) == 1
    sig.emit()
    assert len(sig) == 0


def test_connect_finite_with_one_behaves_like_once():
    calls = []
    sig = dust_riven.Signal("s")
    sig.connect_finite(lambda: calls.append(1), 1)
    sig.emit()
    sig.emit()
    assert calls == [1]

def test_connect_finite_passes_args_on_each_call():
    received = []
    sig = dust_riven.Signal("s")
    sig.connect_finite(lambda a: received.append(a), 2)
    sig.emit(1)
    sig.emit(2)
    sig.emit(3)
    assert received == [1, 2]


def test_connect_finite_disconnect_before_exhausted():
    calls = []
    sig = dust_riven.Signal("s")
    cid = sig.connect_finite(lambda: calls.append(1), 3)
    sig.emit()
    sig.disconnect(cid)
    sig.emit()
    assert calls == [1]
    assert len(sig) == 0


def test_connect_finite_accepts_weak():
    sig = dust_riven.Signal("s")
    class Handler:
        def on_event(self):
            pass
    handler = Handler()
    sig.connect_finite(handler.on_event, 2, weak=True)
    assert len(sig) == 1


def test_connect_finite_rejects_orphan_weak_callback():
    sig = dust_riven.Signal("s")
    class Handler:
        def on_event(self):
            pass
    with pytest.raises(TypeError):
        sig.connect_finite(Handler().on_event, 2, weak=True)


def test_connect_finite_coexists_with_connect_once_and_regular():
    calls = []
    sig = dust_riven.Signal("s")
    sig.connect(lambda: calls.append("regular"))
    sig.connect_once(lambda: calls.append("once"))
    sig.connect_finite(lambda: calls.append("finite"), 2)
    sig.emit()
    sig.emit()
    sig.emit()
    assert calls == [
        "regular", "once", "finite",
        "regular", "finite",
        "regular",
    ]
    assert len(sig) == 1


# --- weak footgun ---

def test_connect_weak_rejects_orphan_bound_method():
    sig = dust_riven.Signal("s")
    class Handler:
        def on_event(self):
            pass
    with pytest.raises(TypeError):
        sig.connect(Handler().on_event, weak=True)


def test_connect_weak_rejects_orphan_lambda():
    sig = dust_riven.Signal("s")
    with pytest.raises(TypeError):
        sig.connect(lambda: None, weak=True)


def test_connect_weak_accepts_callback_with_kept_reference():
    sig = dust_riven.Signal("s")
    class Handler:
        def on_event(self):
            pass
    handler = Handler()
    sig.connect(handler.on_event, weak=True)
    assert len(sig) == 1


def test_connect_weak_rejected_callback_not_added():
    sig = dust_riven.Signal("s")
    class Handler:
        def on_event(self):
            pass
    with pytest.raises(TypeError):
        sig.connect(Handler().on_event, weak=True)
    assert len(sig) == 0


def test_connect_orphan_callback_allowed_when_not_weak():
    sig = dust_riven.Signal("s")
    class Handler:
        def on_event(self):
            pass
    sig.connect(Handler().on_event)
    assert len(sig) == 1


# --- emit on_error ---

def test_emit_default_on_error_is_fast_fail():
    calls = []
    sig = dust_riven.Signal("s")
    sig.connect(lambda: calls.append("first"))
    def bad():
        raise RuntimeError("boom")
    sig.connect(bad)
    sig.connect(lambda: calls.append("third"))
    with pytest.raises(RuntimeError):
        sig.emit()
    assert calls == ["first"]


def test_emit_fast_fail_explicit_stops_after_exception():
    calls = []
    sig = dust_riven.Signal("s")
    sig.connect(lambda: calls.append("first"))
    def bad():
        raise RuntimeError("boom")
    sig.connect(bad)
    sig.connect(lambda: calls.append("third"))
    with pytest.raises(RuntimeError):
        sig.emit(on_error="fast_fail")
    assert calls == ["first"]


def test_emit_fast_fail_returns_list_of_results_when_no_exceptions():
    sig = dust_riven.Signal("s")
    sig.connect(lambda: "a")
    sig.connect(lambda: "b")
    results = sig.emit()
    assert results == ["a", "b"]


def test_emit_collect_runs_all_listeners_despite_exception():
    calls = []
    sig = dust_riven.Signal("s")
    sig.connect(lambda: calls.append("first"))
    def bad():
        raise RuntimeError("boom")
    sig.connect(bad)
    sig.connect(lambda: calls.append("third"))
    sig.emit(on_error="collect")
    assert calls == ["first", "third"]


def test_emit_collect_returns_results_and_exceptions_in_order():
    sig = dust_riven.Signal("s")
    sig.connect(lambda: 1)
    def bad():
        raise ValueError("boom")
    sig.connect(bad)
    sig.connect(lambda: 3)
    results = sig.emit(on_error="collect")
    assert results[0] == 1
    assert isinstance(results[1], ValueError)
    assert results[2] == 3


def test_emit_collect_multiple_exceptions_preserve_order():
    sig = dust_riven.Signal("s")
    def bad1():
        raise ValueError("first")
    def bad2():
        raise KeyError("second")
    sig.connect(bad1)
    sig.connect(bad2)
    results = sig.emit(on_error="collect")
    assert isinstance(results[0], ValueError)
    assert isinstance(results[1], KeyError)


def test_emit_collect_with_no_exceptions_returns_all_results():
    sig = dust_riven.Signal("s")
    sig.connect(lambda: "a")
    sig.connect(lambda: "b")
    assert sig.emit(on_error="collect") == ["a", "b"]


def test_emit_collect_with_no_listeners_returns_empty_list():
    sig = dust_riven.Signal("s")
    assert sig.emit(on_error="collect") == []


def test_emit_collect_removes_exhausted_connect_once_listener():
    sig = dust_riven.Signal("s")
    sig.connect_once(lambda: "once")
    sig.emit(on_error="collect")
    assert len(sig) == 0


def test_emit_collect_removes_dead_weak_listener():
    sig = dust_riven.Signal("s")
    class Handler:
        def on_event(self):
            pass
    handler = Handler()
    sig.connect(handler.on_event, weak=True)
    del handler
    results = sig.emit(on_error="collect")
    assert results == []
    assert len(sig) == 0


def test_emit_invalid_on_error_raises_type_error():
    sig = dust_riven.Signal("s")
    sig.connect(lambda: None)
    with pytest.raises(TypeError):
        sig.emit(on_error="whatever")


def test_emit_invalid_on_error_does_not_call_listeners():
    calls = []
    sig = dust_riven.Signal("s")
    sig.connect(lambda: calls.append(1))
    with pytest.raises(TypeError):
        sig.emit(on_error="whatever")
    assert calls == []


# --- emit_async ---

def test_emit_async_with_no_listeners_does_nothing():
    sig = dust_riven.Signal("s")
    async def run():
        await sig.emit_async()
    asyncio.run(run())


def test_emit_async_calls_sync_listener():
    calls = []
    sig = dust_riven.Signal("s")
    sig.connect(lambda: calls.append("sync"))

    async def run():
        await sig.emit_async()

    asyncio.run(run())
    assert calls == ["sync"]


def test_emit_async_calls_async_listener():
    calls = []
    sig = dust_riven.Signal("s")

    async def handler():
        calls.append("async")

    sig.connect(handler)

    async def run():
        await sig.emit_async()

    asyncio.run(run())
    assert calls == ["async"]


def test_emit_async_calls_mixed_sync_and_async_listeners():
    calls = []
    sig = dust_riven.Signal("s")

    async def async_handler():
        calls.append("async")

    sig.connect(lambda: calls.append("sync"))
    sig.connect(async_handler)

    async def run():
        await sig.emit_async()

    asyncio.run(run())
    assert sorted(calls) == ["async", "sync"]


def test_emit_async_passes_positional_args():
    received = []
    sig = dust_riven.Signal("s")

    async def handler(a, b):
        received.append((a, b))

    sig.connect(handler)

    async def run():
        await sig.emit_async(1, 2)

    asyncio.run(run())
    assert received == [(1, 2)]


def test_emit_async_passes_keyword_args():
    received = []
    sig = dust_riven.Signal("s")

    async def handler(**kw):
        received.append(kw)

    sig.connect(handler)

    async def run():
        await sig.emit_async(x=1, y=2)

    asyncio.run(run())
    assert received == [{"x": 1, "y": 2}]


def test_emit_async_waits_for_async_listener_to_complete():
    state = {"done": False}
    sig = dust_riven.Signal("s")

    async def handler():
        await asyncio.sleep(0.01)
        state["done"] = True

    sig.connect(handler)

    async def run():
        await sig.emit_async()
        assert state["done"] is True

    asyncio.run(run())


def test_emit_async_runs_async_listeners_concurrently():
    sig = dust_riven.Signal("s")
    order = []

    async def slow():
        order.append("slow-start")
        await asyncio.sleep(0.02)
        order.append("slow-end")

    async def fast():
        order.append("fast-start")
        await asyncio.sleep(0.001)
        order.append("fast-end")

    sig.connect(slow)
    sig.connect(fast)

    async def run():
        await sig.emit_async()

    asyncio.run(run())
    # both start before either finishes if run concurrently
    assert order.index("fast-end") < order.index("slow-end")
    assert order.index("slow-start") < order.index("fast-end")


def test_emit_async_propagates_exception_from_async_listener():
    sig = dust_riven.Signal("s")

    async def bad():
        raise ValueError("boom")

    sig.connect(bad)

    async def run():
        await sig.emit_async()

    with pytest.raises(ValueError):
        asyncio.run(run())


def test_emit_async_propagates_exception_from_sync_listener():
    sig = dust_riven.Signal("s")

    def bad():
        raise RuntimeError("boom")

    sig.connect(bad)

    async def run():
        await sig.emit_async()

    with pytest.raises(RuntimeError):
        asyncio.run(run())


def test_emit_async_skips_dead_weak_listener():
    sig = dust_riven.Signal("s")
    calls = []

    class Handler:
        def on_event(self):
            calls.append("called")

    handler = Handler()
    sig.connect(handler.on_event, weak=True)
    del handler

    async def run():
        await sig.emit_async()

    asyncio.run(run())
    assert calls == []
    assert len(sig) == 0


def test_emit_async_connect_once_removed_after_first_emit():
    calls = []
    sig = dust_riven.Signal("s")

    async def handler():
        calls.append(1)

    sig.connect_once(handler)

    async def run():
        await sig.emit_async()
        await sig.emit_async()

    asyncio.run(run())
    assert calls == [1]
    assert len(sig) == 0


def test_emit_async_connect_finite_called_exact_number_of_times():
    counter = {"n": 0}
    sig = dust_riven.Signal("s")

    async def handler():
        counter["n"] += 1

    sig.connect_finite(handler, 2)

    async def run():
        for _ in range(4):
            await sig.emit_async()

    asyncio.run(run())
    assert counter["n"] == 2
    assert len(sig) == 0


def test_emit_async_after_regular_emit_still_works():
    calls = []
    sig = dust_riven.Signal("s")

    async def handler():
        calls.append("async")

    sig.connect(lambda: calls.append("sync"))
    sig.connect(handler)
    sig.emit()

    async def run():
        await sig.emit_async()

    asyncio.run(run())
    assert calls == ["sync", "sync", "async"]


def test_connected_connects_listener():
    sig = dust_riven.Signal("s")
    with sig.connected(lambda: None):
        assert len(sig) == 1


def test_connected_disconnects_on_normal_exit():
    sig = dust_riven.Signal("s")
    with sig.connected(lambda: None):
        pass
    assert len(sig) == 0


def test_connected_disconnects_on_exception():
    sig = dust_riven.Signal("s")
    with pytest.raises(ValueError):
        with sig.connected(lambda: None):
            raise ValueError("boom")
    assert len(sig) == 0


def test_connected_yields_connection_id():
    sig = dust_riven.Signal("s")
    with sig.connected(lambda: None) as cid:
        assert isinstance(cid, int)
        assert sig.disconnect(cid) is True


def test_connected_listener_receives_emit():
    calls = []
    sig = dust_riven.Signal("s")
    with sig.connected(lambda a: calls.append(a)):
        sig.emit(1)
    assert calls == [1]


def test_connected_stops_receiving_after_exit():
    calls = []
    sig = dust_riven.Signal("s")
    with sig.connected(lambda: calls.append(1)):
        sig.emit()
    sig.emit()
    assert calls == [1]


def test_connected_coexists_with_regular_listener():
    calls = []
    sig = dust_riven.Signal("s")
    sig.connect(lambda: calls.append("regular"))
    with sig.connected(lambda: calls.append("temp")):
        sig.emit()
    assert sorted(calls) == ["regular", "temp"]
    calls.clear()
    sig.emit()
    assert calls == ["regular"]


def test_connected_accepts_weak():
    sig = dust_riven.Signal("s")
    class Handler:
        def on_event(self):
            pass
    handler = Handler()
    with sig.connected(handler.on_event, weak=True):
        assert len(sig) == 1
    assert len(sig) == 0


def test_connected_nested_contexts():
    sig = dust_riven.Signal("s")
    with sig.connected(lambda: None):
        assert len(sig) == 1
        with sig.connected(lambda: None):
            assert len(sig) == 2
        assert len(sig) == 1
    assert len(sig) == 0


def test_connected_rejects_non_callable():
    sig = dust_riven.Signal("s")
    with pytest.raises(TypeError):
        sig.connected(42)


def test_connect_default_priority_preserves_fifo_order():
    calls = []
    sig = dust_riven.Signal("s")
    sig.connect(lambda: calls.append("a"))
    sig.connect(lambda: calls.append("b"))
    sig.connect(lambda: calls.append("c"))
    sig.emit()
    assert calls == ["a", "b", "c"]


def test_connect_higher_priority_runs_first():
    calls = []
    sig = dust_riven.Signal("s")
    sig.connect(lambda: calls.append("low"), priority=0)
    sig.connect(lambda: calls.append("high"), priority=10)
    sig.emit()
    assert calls == ["high", "low"]


def test_connect_negative_priority_runs_last():
    calls = []
    sig = dust_riven.Signal("s")
    sig.connect(lambda: calls.append("normal"), priority=0)
    sig.connect(lambda: calls.append("low"), priority=-5)
    sig.emit()
    assert calls == ["normal", "low"]


def test_connect_equal_priority_preserves_insertion_order():
    calls = []
    sig = dust_riven.Signal("s")
    sig.connect(lambda: calls.append("first"), priority=5)
    sig.connect(lambda: calls.append("second"), priority=5)
    sig.connect(lambda: calls.append("third"), priority=5)
    sig.emit()
    assert calls == ["first", "second", "third"]


def test_connect_priority_inserted_between_existing():
    calls = []
    sig = dust_riven.Signal("s")
    sig.connect(lambda: calls.append("high"), priority=10)
    sig.connect(lambda: calls.append("low"), priority=0)
    sig.connect(lambda: calls.append("mid"), priority=5)
    sig.emit()
    assert calls == ["high", "mid", "low"]


def test_connect_once_respects_priority():
    calls = []
    sig = dust_riven.Signal("s")
    sig.connect(lambda: calls.append("regular"), priority=0)
    sig.connect_once(lambda: calls.append("once"), priority=10)
    sig.emit()
    assert calls == ["once", "regular"]


def test_connect_finite_respects_priority():
    calls = []
    sig = dust_riven.Signal("s")
    sig.connect(lambda: calls.append("regular"), priority=0)
    sig.connect_finite(lambda: calls.append("finite"), 2, priority=10)
    sig.emit()
    sig.emit()
    assert calls == ["finite", "regular", "finite", "regular"]


def test_connect_priority_survives_disconnect_of_other_listener():
    calls = []
    sig = dust_riven.Signal("s")
    id_low = sig.connect(lambda: calls.append("low"), priority=0)
    sig.connect(lambda: calls.append("high"), priority=10)
    sig.disconnect(id_low)
    sig.emit()
    assert calls == ["high"]


def test_connect_priority_ordering_with_weak_listener():
    calls = []
    sig = dust_riven.Signal("s")

    class Handler:
        def on_event(self):
            calls.append("weak")

    handler = Handler()
    sig.connect(lambda: calls.append("strong_low"), priority=0)
    sig.connect(handler.on_event, weak=True, priority=10)
    sig.connect(lambda: calls.append("strong_mid"), priority=5)
    sig.emit()
    assert calls == ["weak", "strong_mid", "strong_low"]


def test_connect_priority_ordering_survives_dead_weak_listener():
    calls = []
    sig = dust_riven.Signal("s")

    class Handler:
        def on_event(self):
            calls.append("weak")

    handler = Handler()
    sig.connect(lambda: calls.append("low"), priority=0)
    sig.connect(handler.on_event, weak=True, priority=10)
    sig.connect(lambda: calls.append("mid"), priority=5)
    del handler
    sig.emit()
    assert calls == ["mid", "low"]
    assert len(sig) == 2


def test_connect_default_priority_is_zero():
    calls = []
    sig = dust_riven.Signal("s")
    sig.connect(lambda: calls.append("default"))
    sig.connect(lambda: calls.append("negative"), priority=-1)
    sig.connect(lambda: calls.append("positive"), priority=1)
    sig.emit()
    assert calls == ["positive", "default", "negative"]


def test_connected_respects_priority():
    calls = []
    sig = dust_riven.Signal("s")
    sig.connect(lambda: calls.append("regular"), priority=0)
    with sig.connected(lambda: calls.append("scoped"), priority=10):
        sig.emit()
    assert calls == ["scoped", "regular"]


def test_emit_async_respects_priority_for_sync_listeners():
    calls = []
    sig = dust_riven.Signal("s")
    sig.connect(lambda: calls.append("low"), priority=0)
    sig.connect(lambda: calls.append("high"), priority=10)

    async def run():
        await sig.emit_async()

    asyncio.run(run())
    assert calls == ["high", "low"]


def test_emit_async_priority_affects_start_order_of_async_listeners():
    order = []
    sig = dust_riven.Signal("s")

    async def low():
        order.append("low-start")

    async def high():
        order.append("high-start")

    sig.connect(low, priority=0)
    sig.connect(high, priority=10)

    async def run():
        await sig.emit_async()

    asyncio.run(run())
    assert order.index("high-start") < order.index("low-start")