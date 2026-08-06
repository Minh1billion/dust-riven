use pyo3::prelude::*;

use crate::signal::Signal;

#[pyclass]
pub(crate) struct SignalConnection {
    pub(crate) signal: Py<Signal>,
    pub(crate) id: u64,
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