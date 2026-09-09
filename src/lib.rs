mod voprf_core;
use voprf_core::*;
#[cfg(feature = "extension-module")]
mod python {
    use super::*;
    use pyo3::exceptions::PyValueError;
    use pyo3::prelude::*;

    #[pyfunction]
    fn blind(input_data: &[u8]) -> PyResult<(Vec<u8>, Vec<u8>)> {
        blind_inner(input_data).map_err(|error| PyValueError::new_err(error.to_string()))
    }

    #[pyfunction]
    fn validate_public_key(server_public_key: &[u8]) -> PyResult<()> {
        validate_public_key_inner(server_public_key)
            .map_err(|error| PyValueError::new_err(error.to_string()))
    }

    #[pyfunction]
    fn finalize(
        input_data: &[u8],
        client_state: &[u8],
        evaluated_element: &[u8],
        proof: &[u8],
        server_public_key: &[u8],
    ) -> PyResult<Vec<u8>> {
        finalize_inner(
            input_data,
            client_state,
            evaluated_element,
            proof,
            server_public_key,
        )
        .map_err(|error| PyValueError::new_err(error.to_string()))
    }

    #[pymodule]
    fn omneum_oprf(m: &Bound<'_, PyModule>) -> PyResult<()> {
        m.add_function(wrap_pyfunction!(blind, m)?)?;
        m.add_function(wrap_pyfunction!(validate_public_key, m)?)?;
        m.add_function(wrap_pyfunction!(finalize, m)?)?;

        Ok(())
    }
}

#[cfg(test)]
mod fuzz;

#[cfg(all(feature = "daemon", any(target_os = "linux", target_os = "macos")))]
pub mod daemon;
