use pyo3::prelude::*;
use pyo3::types::{PyAny, PyTuple};
use parking_lot::RwLock;
use slotmap::{SlotMap, DefaultKey};
use futures::stream::{FuturesUnordered, StreamExt};

struct ListenerEntry {
    callback: Py<PyAny>,
    once: bool,
}

#[pyclass]
struct Signal {
    listeners: RwLock<SlotMap<DefaultKey, ListenerEntry>>,
}

impl Signal {
    fn insert_listener(&self, callback: Py<PyAny>, once: bool) -> u64 {
        let entry = ListenerEntry { callback, once };
        let key = self.listeners.write().insert(entry);
        key_to_u64(key)
    }
}

#[pymethods]
impl Signal {
    #[new]
    fn new() -> Self {
        Signal {
            listeners: RwLock::new(SlotMap::new()),
        }
    }

    fn connect(&self, callback: Py<PyAny>) -> u64 {
        self.insert_listener(callback, false)
    }

    fn once(&self, callback: Py<PyAny>) -> u64 {
        self.insert_listener(callback, true)
    }

    fn disconnect(&self, handle: u64) {
        let key = u64_to_key(handle);
        self.listeners.write().remove(key);
    }

    #[pyo3(signature = (*args, on_error="collect"))]
    fn emit(&self, py: Python<'_>, args: Bound<'_, PyTuple>, on_error: &str) -> PyResult<()> {
        validate_on_error(on_error)?;

        let snapshot = take_emit_snapshot(&self.listeners, py);

        let asyncio = py.import("asyncio")?;
        let mut first_error = None;

        for listener in &snapshot {
            match listener.call1(py, &args) {
                Ok(result) => {
                    let result_bound = result.bind(py);
                    let is_coroutine = asyncio
                        .call_method1("iscoroutine", (result_bound,))?
                        .extract::<bool>()?;

                    if is_coroutine {
                        let _ = result_bound.call_method0("close");

                        let listener_repr = listener
                            .bind(py)
                            .repr()
                            .map(|r| r.to_string())
                            .unwrap_or_else(|_| "<listener>".to_string());

                        let err = pyo3::exceptions::PyTypeError::new_err(format!(
                            "listener {} is an async function but was registered for \
                             synchronous emit() — the coroutine will never run. \
                             Use emit_async() for async listeners.",
                            listener_repr
                        ));

                        if on_error == "fail_fast" {
                            return Err(err);
                        }

                        if first_error.is_none() {
                            first_error = Some(err);
                        }
                    }
                }
                Err(e) => {
                    if on_error == "fail_fast" {
                        return Err(e);
                    }

                    if first_error.is_none() {
                        first_error = Some(e);
                    }
                }
            }
        }

        match first_error {
            Some(e) => Err(e),
            None => Ok(()),
        }
    }

    #[pyo3(signature = (*args, on_error="collect"))]
    fn emit_async<'py>(
        &self,
        py: Python<'py>,
        args: Bound<'py, PyTuple>,
        on_error: &str,
    ) -> PyResult<Bound<'py, PyAny>> {
        validate_on_error(on_error)?;

        let snapshot = take_emit_snapshot(&self.listeners, py);
        let args: Py<PyTuple> = args.unbind();
        let on_error = on_error.to_string();

        pyo3_async_runtimes::tokio::future_into_py(py, async move {
            let mut pending = Vec::new();
            let mut first_error: Option<PyErr> = None;

            let dispatch_result = Python::attach(|py| -> PyResult<()> {
                let asyncio = py.import("asyncio")?;
                let args = args.bind(py);

                for listener in &snapshot {
                    match listener.call1(py, args) {
                        Ok(result) => {
                            let result_bound = result.bind(py);
                            let is_coroutine = asyncio
                                .call_method1("iscoroutine", (result_bound,))?
                                .extract::<bool>()?;

                            if is_coroutine {
                                pending.push(pyo3_async_runtimes::tokio::into_future(
                                    result_bound.clone(),
                                )?);
                            }
                        }
                        Err(e) => {
                            if on_error == "fail_fast" {
                                return Err(e);
                            }

                            if first_error.is_none() {
                                first_error = Some(e);
                            }
                        }
                    }
                }
                Ok(())
            });

            if let Err(e) = dispatch_result {
                return Err(e);
            }

            if on_error == "fail_fast" {
                let mut unordered: FuturesUnordered<_> = pending.into_iter().collect();
                let mut fail_fast_error = None;

                while let Some(result) = unordered.next().await {
                    if let Err(e) = result {
                        fail_fast_error = Some(e);
                        break;
                    }
                }

                return match fail_fast_error.or(first_error) {
                    Some(e) => Err(e),
                    None => Ok(()),
                };
            }

            let results = futures::future::join_all(pending).await;

            for result in results {
                if let Err(e) = result {
                    if first_error.is_none() {
                        first_error = Some(e);
                    }
                }
            }

            match first_error {
                Some(e) => Err(e),
                None => Ok(()),
            }
        })
    }
}

fn take_emit_snapshot(
    listeners: &RwLock<SlotMap<DefaultKey, ListenerEntry>>,
    py: Python<'_>,
) -> Vec<Py<PyAny>> {
    {
        let guard = listeners.read();
        if !guard.values().any(|entry| entry.once) {
            return guard.values().map(|entry| entry.callback.clone_ref(py)).collect();
        }
    }

    let mut guard = listeners.write();
    let once_keys: Vec<DefaultKey> = guard
        .iter()
        .filter(|(_, entry)| entry.once)
        .map(|(key, _)| key)
        .collect();

    let snapshot: Vec<Py<PyAny>> = guard
        .values()
        .map(|entry| entry.callback.clone_ref(py))
        .collect();

    for key in once_keys {
        guard.remove(key);
    }

    snapshot
}

fn key_to_u64(key: DefaultKey) -> u64 {
    use slotmap::Key;
    key.data().as_ffi()
}

fn u64_to_key(value: u64) -> DefaultKey {
    use slotmap::KeyData;
    KeyData::from_ffi(value).into()
}

fn validate_on_error(on_error: &str) -> PyResult<()> {
    match on_error {
        "collect" | "fail_fast" => Ok(()),
        other => Err(pyo3::exceptions::PyValueError::new_err(format!(
            "on_error must be 'collect' or 'fail_fast', got: {:?}",
            other
        ))),
    }
}

#[pymodule]
fn dust_riven(m: &Bound<'_, PyModule>) -> PyResult<()> {
    m.add_class::<Signal>()?;
    Ok(())
}