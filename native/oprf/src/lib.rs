use pyo3::exceptions::PyValueError;
use pyo3::prelude::*;
use rand::rngs::OsRng;
use voprf::{BlindedElement, EvaluationElement, OprfClient, OprfServer, Ristretto255};

/// Client-side RFC 9497 blinding.
///
/// Input:
///  canonical serialized assertion bytes
///
/// Returns:
///  (blinded_element, client_state)
#[pyfunction]
fn blind(input_data: &[u8]) -> PyResult<(Vec<u8>, Vec<u8>)> {
    let blind_result =
        OprfClient::<Ristretto255>::blind(input_data, &mut OsRng).map_err(|error| {
            PyValueError::new_err(format!("RFC 9497 client blinding failed: {error}"))
        })?;

    Ok((
        blind_result.message.serialize().to_vec(),
        blind_result.state.serialize().to_vec(),
    ))
}

/// Server-side RFC 9497 evaluation.
///
/// Input:
///  server private key
///  blinded element
///
/// Returns:
///  evaluated element
#[pyfunction]
fn evaluate(server_key: &[u8], blinded_element: &[u8]) -> PyResult<Vec<u8>> {
    let server = OprfServer::<Ristretto255>::new_with_key(server_key)
        .map_err(|error| PyValueError::new_err(format!("Invalid RFC 9497 server key: {error}")))?;

    let blinded_element =
        BlindedElement::<Ristretto255>::deserialize(blinded_element).map_err(|error| {
            PyValueError::new_err(format!("Malformed RFC 9497 blinded element: {error}"))
        })?;

    Ok(server.blind_evaluate(&blinded_element).serialize().to_vec())
}

/// Client-side RFC 9497 finalization.
///
/// Input:
///  original input
///  client state
///  evaluated element
///
/// Returns:
///  deterministic OPRF output
#[pyfunction]
fn finalize(input_data: &[u8], client_state: &[u8], evaluated_element: &[u8]) -> PyResult<Vec<u8>> {
    let client = OprfClient::<Ristretto255>::deserialize(client_state).map_err(|error| {
        PyValueError::new_err(format!("Malformed RFC 9497 client state: {error}"))
    })?;

    let evaluated_element = EvaluationElement::<Ristretto255>::deserialize(evaluated_element)
        .map_err(|error| {
            PyValueError::new_err(format!("Malformed RFC 9497 evaluation element: {error}"))
        })?;

    client
        .finalize(input_data, &evaluated_element)
        .map(|output| output.to_vec())
        .map_err(|error| {
            PyValueError::new_err(format!("RFC 9497 client finalization failed: {error}"))
        })
}

#[pymodule]
fn verity_oprf(m: &Bound<'_, PyModule>) -> PyResult<()> {
    m.add_function(wrap_pyfunction!(blind, m)?)?;
    m.add_function(wrap_pyfunction!(evaluate, m)?)?;
    m.add_function(wrap_pyfunction!(finalize, m)?)?;

    Ok(())
}
