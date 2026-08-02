use std::collections::HashSet;
use std::sync::atomic::{AtomicU64, Ordering};

use parking_lot::RwLock;
use once_cell::sync::OnceCell;
use pyo3::{
    exceptions::PyTypeError,
    prelude::*,
    types::{PyDict, PyTuple},
};
use smallvec::SmallVec;

enum Callback {
    Strong(Py<PyAny>),
    Weak(Py<PyAny>),
}

struct CallbackEntry {
    id: u64,
    priority: i32,
    callback: Callback,
    remaining: Option<AtomicU64>,
}

fn insert_sorted(callbacks: &mut SmallVec<[CallbackEntry; 4]>, entry: CallbackEntry) {
    let pos = callbacks.partition_point(|e| e.priority >= entry.priority);
    callbacks.insert(pos, entry);
}

enum PendingCallback {
    Resolved(Py<PyAny>),
    Weak(u64, Py<PyAny>),
}

#[pyclass]
struct SignalConnection {
    signal: Py<Signal>,
    id: u64,
}

#[pymethods]
impl SignalConnection {
    fn __enter__(&self) -> u64 {
        self.id
    }

    fn __exit__(
        &self,
        py: Python<'_>,
        _exc_type: Bound<'_, PyAny>,
        _exc_val: Bound<'_, PyAny>,
        _exc_tb: Bound<'_, PyAny>,
    ) -> PyResult<bool> {
        self.signal.borrow(py).disconnect(self.id)?;
        Ok(false)
    }
}

#[pyclass(frozen)]
struct Signal {
    name: Option<String>,
    next_id: AtomicU64,
    callbacks: RwLock<SmallVec<[CallbackEntry; 4]>>,
    weakref_mod: OnceCell<Py<PyModule>>,
    asyncio_mod: OnceCell<Py<PyModule>>,
    immediate_fn: OnceCell<Py<PyAny>>,
}

fn saturating_dec(remaining: &AtomicU64) -> Option<bool> {
    let mut current = remaining.load(Ordering::Relaxed);
    loop {
        if current == 0 {
            return None;
        }
        let new = current - 1;
        match remaining.compare_exchange_weak(current, new, Ordering::Relaxed, Ordering::Relaxed) {
            Ok(_) => return Some(new == 0),
            Err(observed) => current = observed,
        }
    }
}

impl Signal {
    fn get_immediate_fn(&self, py: Python<'_>) -> PyResult<Py<PyAny>> {
        let f = self.immediate_fn.get_or_try_init(|| -> PyResult<Py<PyAny>> {
            let module = PyModule::from_code(
                py,
                c"async def _dust_riven_immediate(value):\n    return value\n",
                c"dust_riven_internal.py",
                c"dust_riven_internal",
            )?;
            let func = module.getattr("_dust_riven_immediate")?;
            Ok(func.unbind())
        })?;
        Ok(f.clone_ref(py))
    }

    fn get_asyncio(&self, py: Python<'_>) -> PyResult<Py<PyModule>> {
        let m = self
            .asyncio_mod
            .get_or_try_init(|| py.import("asyncio").map(|m| m.unbind()))?;
        Ok(m.clone_ref(py))
    }
}

#[pymethods]
impl Signal {
    #[new]
    #[pyo3(signature = (name=None))]
    fn new(name: Option<String>) -> Signal {
        Signal {
            name,
            next_id: AtomicU64::new(0),
            callbacks: RwLock::new(SmallVec::new()),
            weakref_mod: OnceCell::new(),
            asyncio_mod: OnceCell::new(),
            immediate_fn: OnceCell::new(),
        }
    }

    #[pyo3(signature = (callback, weak=false, priority=0))]
    fn connect(&self, py: Python<'_>, callback: Py<PyAny>, weak: bool, priority: i32) -> PyResult<u64> {
        if !callback.bind(py).is_callable() {
            return Err(PyTypeError::new_err("Callback must be a function."));
        }
        let callback = if weak {
            let bound_cb = callback.bind(py);
            let is_bound_method = bound_cb.hasattr("__self__")?;
            let (refcount, refcount_threshold): (usize, usize) = if is_bound_method {
                let slf = bound_cb.getattr("__self__")?;
                let rc = py.import("sys")?.call_method1("getrefcount", (slf,))?.extract()?;
                (rc, 2)
            } else {
                let rc = py.import("sys")?.call_method1("getrefcount", (bound_cb,))?.extract()?;
                (rc, 3)
            };
            if refcount <= refcount_threshold {
                return Err(PyTypeError::new_err(
                    "Callback passed with weak=True has no other strong reference and would be garbage collected immediately.",
                ));
            }
            let weakref_mod = self
                .weakref_mod
                .get_or_try_init(|| py.import("weakref").map(|m| m.unbind()))?;
            let ctor = if is_bound_method { "WeakMethod" } else { "ref" };
            let weakref_obj = weakref_mod.bind(py).call_method1(ctor, (callback,))?;
            Callback::Weak(weakref_obj.unbind())
        } else {
            Callback::Strong(callback)
        };
        let id = self.next_id.fetch_add(1, Ordering::Relaxed);
        insert_sorted(&mut self.callbacks.write(), CallbackEntry { id, priority, callback, remaining: None });
        Ok(id)
    }

    #[pyo3(signature = (callback, weak=false, priority=0))]
    fn connect_once(&self, py: Python<'_>, callback: Py<PyAny>, weak: bool, priority: i32) -> PyResult<u64> {
        if !callback.bind(py).is_callable() {
            return Err(PyTypeError::new_err("Callback must be a function."));
        }
        let callback = if weak {
            let bound_cb = callback.bind(py);
            let is_bound_method = bound_cb.hasattr("__self__")?;
            let (refcount, refcount_threshold): (usize, usize) = if is_bound_method {
                let slf = bound_cb.getattr("__self__")?;
                let rc = py.import("sys")?.call_method1("getrefcount", (slf,))?.extract()?;
                (rc, 2)
            } else {
                let rc = py.import("sys")?.call_method1("getrefcount", (bound_cb,))?.extract()?;
                (rc, 3)
            };
            if refcount <= refcount_threshold {
                return Err(PyTypeError::new_err(
                    "Callback passed with weak=True has no other strong reference and would be garbage collected immediately.",
                ));
            }
            let weakref_mod = self
                .weakref_mod
                .get_or_try_init(|| py.import("weakref").map(|m| m.unbind()))?;
            let ctor = if is_bound_method { "WeakMethod" } else { "ref" };
            let weakref_obj = weakref_mod.bind(py).call_method1(ctor, (callback,))?;
            Callback::Weak(weakref_obj.unbind())
        } else {
            Callback::Strong(callback)
        };
        let id = self.next_id.fetch_add(1, Ordering::Relaxed);
        insert_sorted(&mut self.callbacks.write(), CallbackEntry { id, priority, callback, remaining: Some(AtomicU64::new(1)) });
        Ok(id)
    }

    #[pyo3(signature = (callback, times, weak=false, priority=0))]
    fn connect_finite(&self, py: Python<'_>, callback: Py<PyAny>, times: u64, weak: bool, priority: i32) -> PyResult<u64> {
        if !callback.bind(py).is_callable() {
            return Err(PyTypeError::new_err("Callback must be a function."));
        }
        if times == 0 {
            return Err(PyTypeError::new_err("times must be greater than zero."));
        }
        let callback = if weak {
            let bound_cb = callback.bind(py);
            let is_bound_method = bound_cb.hasattr("__self__")?;
            let (refcount, refcount_threshold): (usize, usize) = if is_bound_method {
                let slf = bound_cb.getattr("__self__")?;
                let rc = py.import("sys")?.call_method1("getrefcount", (slf,))?.extract()?;
                (rc, 2)
            } else {
                let rc = py.import("sys")?.call_method1("getrefcount", (bound_cb,))?.extract()?;
                (rc, 3)
            };
            if refcount <= refcount_threshold {
                return Err(PyTypeError::new_err(
                    "Callback passed with weak=True has no other strong reference and would be garbage collected immediately.",
                ));
            }
            let weakref_mod = self
                .weakref_mod
                .get_or_try_init(|| py.import("weakref").map(|m| m.unbind()))?;
            let ctor = if is_bound_method { "WeakMethod" } else { "ref" };
            let weakref_obj = weakref_mod.bind(py).call_method1(ctor, (callback,))?;
            Callback::Weak(weakref_obj.unbind())
        } else {
            Callback::Strong(callback)
        };
        let id = self.next_id.fetch_add(1, Ordering::Relaxed);
        insert_sorted(&mut self.callbacks.write(), CallbackEntry { id, priority, callback, remaining: Some(AtomicU64::new(times)) });
        Ok(id)
    }

    fn disconnect(&self, id: u64) -> PyResult<bool> {
        let mut guard = self.callbacks.write();
        let before = guard.len();
        guard.retain(|entry| entry.id != id);
        Ok(guard.len() != before)
    }

    #[pyo3(signature = (callback, weak=false, priority=0))]
    fn connected(
        slf: Py<Self>,
        py: Python<'_>,
        callback: Py<PyAny>,
        weak: bool,
        priority: i32,
    ) -> PyResult<SignalConnection> {
        let id = slf.borrow(py).connect(py, callback, weak, priority)?;
        Ok(SignalConnection { signal: slf, id })
    }

    #[pyo3(signature = (*args, on_error="fast_fail", **kwargs))]
    fn emit(
        &self,
        py: Python<'_>,
        args: &Bound<'_, PyTuple>,
        on_error: &str,
        kwargs: Option<&Bound<'_, PyDict>>,
    ) -> PyResult<Py<PyAny>> {
        if on_error != "fast_fail" && on_error != "collect" {
            return Err(PyTypeError::new_err("on_error must be 'fast_fail' or 'collect'."));
        }

        let mut dead_ids = HashSet::new();
        let mut pending = Vec::new();

        let guard = self.callbacks.read();
        for entry in guard.iter() {
            if let Some(remaining) = &entry.remaining {
                match saturating_dec(remaining) {
                    None => {
                        dead_ids.insert(entry.id);
                        continue;
                    }
                    Some(true) => {
                        dead_ids.insert(entry.id);
                    }
                    Some(false) => {}
                }
            }
            match &entry.callback {
                Callback::Strong(callback) => pending.push(PendingCallback::Resolved(callback.clone_ref(py))),
                Callback::Weak(weakref_obj) => pending.push(PendingCallback::Weak(entry.id, weakref_obj.clone_ref(py))),
            }
        }
        drop(guard);

        let mut snapshot = Vec::with_capacity(pending.len());
        for item in pending {
            match item {
                PendingCallback::Resolved(callback) => snapshot.push(callback),
                PendingCallback::Weak(id, weakref_obj) => {
                    let referent = weakref_obj.call0(py)?;
                    if referent.is_none(py) {
                        dead_ids.insert(id);
                    } else {
                        snapshot.push(referent);
                    }
                }
            }
        }

        if !dead_ids.is_empty() {
            self.callbacks
                .write()
                .retain(|entry| !dead_ids.contains(&entry.id));
        }

        let mut results: Vec<Py<PyAny>> = Vec::with_capacity(snapshot.len());
        for callback in snapshot {
            match callback.call(py, args, kwargs) {
                Ok(result) => results.push(result),
                Err(e) => {
                    if on_error == "fast_fail" {
                        return Err(e);
                    }
                    results.push(e.value(py).clone().unbind().into());
                }
            }
        }

        Ok(pyo3::types::PyList::new(py, results)?.unbind().into())
    }

    #[pyo3(signature = (*args, **kwargs))]
    fn emit_async(
        &self,
        py: Python<'_>,
        args: &Bound<'_, PyTuple>,
        kwargs: Option<&Bound<'_, PyDict>>,
    ) -> PyResult<Py<PyAny>> {
        let mut dead_ids = HashSet::new();
        let mut pending = Vec::new();

        let guard = self.callbacks.read();
        for entry in guard.iter() {
            if let Some(remaining) = &entry.remaining {
                match saturating_dec(remaining) {
                    None => {
                        dead_ids.insert(entry.id);
                        continue;
                    }
                    Some(true) => {
                        dead_ids.insert(entry.id);
                    }
                    Some(false) => {}
                }
            }
            match &entry.callback {
                Callback::Strong(callback) => pending.push(PendingCallback::Resolved(callback.clone_ref(py))),
                Callback::Weak(weakref_obj) => pending.push(PendingCallback::Weak(entry.id, weakref_obj.clone_ref(py))),
            }
        }
        drop(guard);

        let mut snapshot = Vec::with_capacity(pending.len());
        for item in pending {
            match item {
                PendingCallback::Resolved(callback) => snapshot.push(callback),
                PendingCallback::Weak(id, weakref_obj) => {
                    let referent = weakref_obj.call0(py)?;
                    if referent.is_none(py) {
                        dead_ids.insert(id);
                    } else {
                        snapshot.push(referent);
                    }
                }
            }
        }

        if !dead_ids.is_empty() {
            self.callbacks
                .write()
                .retain(|entry| !dead_ids.contains(&entry.id));
        }

        let mut awaitables: Vec<Py<PyAny>> = Vec::with_capacity(snapshot.len());
        for callback in snapshot {
            let result = match callback.call(py, args, kwargs) {
                Ok(result) => result,
                Err(e) => {
                    for obj in awaitables {
                        let bound = obj.bind(py);
                        if bound.hasattr("close")? {
                            let _ = bound.call_method0("close");
                        }
                    }
                    return Err(e);
                }
            };
            if result.bind(py).hasattr("__await__")? {
                awaitables.push(result);
            }
        }

        let asyncio = self.get_asyncio(py)?;
        asyncio.bind(py).call_method0("get_running_loop")?;

        if awaitables.is_empty() {
            let immediate = self.get_immediate_fn(py)?;
            let empty_list = pyo3::types::PyList::empty(py);
            let coro = immediate.bind(py).call1((empty_list,))?;
            return Ok(coro.unbind());
        }

        let awaitables_tuple = pyo3::types::PyTuple::new(py, awaitables)?;
        let gathered = asyncio.bind(py).call_method1("gather", awaitables_tuple)?;
        Ok(gathered.unbind())
    }

    fn __traverse__(&self, visit: pyo3::PyVisit<'_>) -> Result<(), pyo3::PyTraverseError> {
        let guard = self.callbacks.read();
        for entry in guard.iter() {
            match &entry.callback {
                Callback::Strong(cb) => visit.call(cb)?,
                Callback::Weak(w) => visit.call(w)?,
            }
        }
        drop(guard);
        if let Some(f) = self.immediate_fn.get() {
            visit.call(f)?;
        }
        Ok(())
    }

    fn __clear__(&self) {
        self.callbacks.write().clear();
    }

    fn __len__(&self) -> usize {
        self.callbacks.read().len()
    }

    fn __repr__(&self) -> String {
        let listeners = self.callbacks.read().len();
        match &self.name {
            Some(name) => format!("Signal(name={:?}, listeners={})", name, listeners),
            None => format!("Signal(name=None, listeners={})", listeners),
        }
    }
}

#[pymodule]
fn dust_riven(m: &Bound<'_, PyModule>) -> PyResult<()> {
    m.add_class::<Signal>()?;
    m.add_class::<SignalConnection>()?;
    Ok(())
}