use pyo3::prelude::*;
use pyo3::types::{PyAny, PyTuple};
use std::sync::RwLock;
use slotmap::{SlotMap, DefaultKey};

#[pyclass]
struct Signal {
    listeners: RwLock<SlotMap<DefaultKey, Py<PyAny>>>,
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
        let key = self.listeners.write().unwrap().insert(callback);
        key_to_u64(key)
    }

    fn disconnect(&self, handle: u64) {
        let key = u64_to_key(handle);
        self.listeners.write().unwrap().remove(key);
    }

    #[pyo3(signature = (*args))]
    fn emit(&self, py: Python<'_>, args: Bound<'_, PyTuple>) -> PyResult<()> {
        let snapshot: Vec<Py<PyAny>> = self.listeners.read().unwrap()
            .values()
            .map(|obj| obj.clone_ref(py))
            .collect();

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
                        err.print(py);

                        if first_error.is_none() {
                            first_error = Some(err);
                        }
                    }
                }
                Err(e) => {
                    e.print(py);

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

    #[pyo3(signature = (*args))]
    fn emit_async<'py>(
        &self,
        py: Python<'py>,
        args: Bound<'py, PyTuple>,
    ) -> PyResult<Bound<'py, PyAny>> {
        let snapshot: Vec<Py<PyAny>> = self.listeners.read().unwrap()
            .values()
            .map(|obj| obj.clone_ref(py))
            .collect();
        let args: Py<PyTuple> = args.unbind();

        pyo3_async_runtimes::tokio::future_into_py(py, async move {
            let mut pending = Vec::new();
            let mut first_error: Option<PyErr> = None;

            Python::attach(|py| -> PyResult<()> {
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
                            e.print(py);
                            if first_error.is_none() {
                                first_error = Some(e);
                            }
                        }
                    }
                }
                Ok(())
            })?;

            let results = futures::future::join_all(pending).await;

            Python::attach(|py| {
                for result in results {
                    if let Err(e) = result {
                        e.print(py);
                        if first_error.is_none() {
                            first_error = Some(e);
                        }
                    }
                }
            });

            match first_error {
                Some(e) => Err(e),
                None => Ok(()),
            }
        })
    }
}

fn key_to_u64(key: DefaultKey) -> u64 {
    use slotmap::Key;
    key.data().as_ffi()
}

fn u64_to_key(value: u64) -> DefaultKey {
    use slotmap::KeyData;
    KeyData::from_ffi(value).into()
}

#[pymodule]
fn dust_riven(m: &Bound<'_, PyModule>) -> PyResult<()> {
    m.add_class::<Signal>()?;
    Ok(())
}