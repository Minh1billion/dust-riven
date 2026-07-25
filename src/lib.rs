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

            let mut first_error = None;

            for listener in &snapshot {
                if let Err(e) = listener.call1(py, &args) {
                    e.print(py);

                    if first_error.is_none() {
                        first_error = Some(e);
                    }
                }
            }
            
            match first_error {
                Some(e) => Err(e),
                None => Ok(()),
            }
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