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
    callback: Callback,
    remaining: Option<AtomicU64>,
}

#[pyclass(frozen)]
struct Signal {
    name: String,
    next_id: AtomicU64,
    callbacks: RwLock<SmallVec<[CallbackEntry; 4]>>,
    weakref_mod: OnceCell<Py<PyModule>>,
}

#[pymethods]
impl Signal {
    #[new]
    fn new(name: String) -> Signal {
        Signal {
            name,
            next_id: AtomicU64::new(0),
            callbacks: RwLock::new(SmallVec::new()),
            weakref_mod: OnceCell::new(),
        }
    }

    #[pyo3(signature = (callback, weak=false))]
    fn connect(&self, py: Python<'_>, callback: Py<PyAny>, weak: bool) -> PyResult<u64> {
        if !callback.bind(py).is_callable() {
            return Err(PyTypeError::new_err("Callback must be a function."));
        }
        let callback = if weak {
            let weakref_mod = self
                .weakref_mod
                .get_or_try_init(|| py.import("weakref").map(|m| m.unbind()))?;
            let weakref_obj = weakref_mod.bind(py).call_method1("ref", (callback,))?;
            Callback::Weak(weakref_obj.unbind())
        } else {
            Callback::Strong(callback)
        };
        let id = self.next_id.fetch_add(1, Ordering::Relaxed);
        self.callbacks.write().push(CallbackEntry { id, callback, remaining: None });
        Ok(id)
    }

    #[pyo3(signature = (callback, weak=false))]
    fn connect_once(&self, py: Python<'_>, callback: Py<PyAny>, weak: bool) -> PyResult<u64> {
        if !callback.bind(py).is_callable() {
            return Err(PyTypeError::new_err("Callback must be a function."));
        }
        let callback = if weak {
            let weakref_mod = self
                .weakref_mod
                .get_or_try_init(|| py.import("weakref").map(|m| m.unbind()))?;
            let weakref_obj = weakref_mod.bind(py).call_method1("ref", (callback,))?;
            Callback::Weak(weakref_obj.unbind())
        } else {
            Callback::Strong(callback)
        };
        let id = self.next_id.fetch_add(1, Ordering::Relaxed);
        self.callbacks.write().push(CallbackEntry { id, callback, remaining: Some(AtomicU64::new(1)) });
        Ok(id)
    }

    #[pyo3(signature = (callback, times, weak=false))]
    fn connect_finite(&self, py: Python<'_>, callback: Py<PyAny>, times: u64, weak: bool) -> PyResult<u64> {
        if !callback.bind(py).is_callable() {
            return Err(PyTypeError::new_err("Callback must be a function."));
        }
        if times == 0 {
            return Err(PyTypeError::new_err("times must be greater than zero."));
        }
        let callback = if weak {
            let weakref_mod = self
                .weakref_mod
                .get_or_try_init(|| py.import("weakref").map(|m| m.unbind()))?;
            let weakref_obj = weakref_mod.bind(py).call_method1("ref", (callback,))?;
            Callback::Weak(weakref_obj.unbind())
        } else {
            Callback::Strong(callback)
        };
        let id = self.next_id.fetch_add(1, Ordering::Relaxed);
        self.callbacks.write().push(CallbackEntry { id, callback, remaining: Some(AtomicU64::new(times)) });
        Ok(id)
    }

    fn disconnect(&self, id: u64) -> PyResult<bool> {
        let mut guard = self.callbacks.write();
        let before = guard.len();
        guard.retain(|entry| entry.id != id);
        Ok(guard.len() != before)
    }

    #[pyo3(signature = (*args, **kwargs))]
    fn emit(
        &self,
        py: Python<'_>,
        args: &Bound<'_, PyTuple>,
        kwargs: Option<&Bound<'_, PyDict>>,
    ) -> PyResult<()> {
        let guard = self.callbacks.read();
        let mut dead_ids = HashSet::new();
        let mut snapshot = Vec::with_capacity(guard.len());
        for entry in guard.iter() {
            if let Some(remaining) = &entry.remaining {
                let prev = remaining.fetch_sub(1, Ordering::Relaxed);
                if prev == 0 {
                    dead_ids.insert(entry.id);
                    continue;
                }
                if prev == 1 {
                    dead_ids.insert(entry.id);
                }
            }
            match &entry.callback {
                Callback::Strong(callback) => snapshot.push(callback.clone_ref(py)),
                Callback::Weak(weakref_obj) => {
                    let referent = weakref_obj.call0(py)?;
                    if referent.is_none(py) {
                        dead_ids.insert(entry.id);
                    } else {
                        snapshot.push(referent);
                    }
                }
            }
        }
        drop(guard);

        if !dead_ids.is_empty() {
            self.callbacks
                .write()
                .retain(|entry| !dead_ids.contains(&entry.id));
        }

        for callback in snapshot {
            callback.call(py, args, kwargs)?;
        }
        Ok(())
    }

    fn __len__(&self) -> usize {
        self.callbacks.read().len()
    }

    fn __repr__(&self) -> String {
        format!("Signal(name={:?}, listeners={})", self.name, self.callbacks.read().len())
    }
}

#[pymodule]
fn dust_riven(m: &Bound<'_, PyModule>) -> PyResult<()> {
    m.add_class::<Signal>()?;
    Ok(())
}