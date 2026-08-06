mod callback;
mod connection;
mod signal;

use pyo3::prelude::*;

use connection::SignalConnection;
use signal::Signal;

#[pymodule]
fn dust_riven(m: &Bound<'_, PyModule>) -> PyResult<()> {
    m.add_class::<Signal>()?;
    m.add_class::<SignalConnection>()?;
    Ok(())
}