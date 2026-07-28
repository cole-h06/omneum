use std::fmt;

use pyo3::exceptions::PyValueError;
use pyo3::prelude::*;
use rand::rngs::OsRng;
use voprf::{
    BlindedElement, Error as VoprfError, EvaluationElement, OprfClient, OprfServer, Ristretto255,
};

const ELEMENT_LENGTH: usize = 32;
const MAX_INPUT_LENGTH: usize = 65_534;

enum OprfError {
    InvalidLength { name: &'static str, length: usize },
    InputEmpty,
    InputTooLong(usize),
    Blind(VoprfError),
    ServerKey(VoprfError),
    BlindedElement(VoprfError),
    ClientState(VoprfError),
    EvaluationElement(VoprfError),
    Finalize(VoprfError),
}

impl fmt::Display for OprfError {
    fn fmt(&self, formatter: &mut fmt::Formatter<'_>) -> fmt::Result {
        match self {
            Self::InvalidLength { name, length } => {
                write!(
                    formatter,
                    "{name} must be {ELEMENT_LENGTH} bytes; received {length}"
                )
            }
            Self::InputEmpty => write!(formatter, "RFC 9497 private input must not be empty"),
            Self::InputTooLong(length) => write!(
                formatter,
                "RFC 9497 private input must be at most {MAX_INPUT_LENGTH} bytes; received {length}"
            ),
            Self::Blind(error) => {
                write!(formatter, "RFC 9497 client blinding failed: {error}")
            }
            Self::ServerKey(error) => {
                write!(formatter, "Invalid RFC 9497 server key: {error}")
            }
            Self::BlindedElement(error) => {
                write!(formatter, "Malformed RFC 9497 blinded element: {error}")
            }
            Self::ClientState(error) => {
                write!(formatter, "Malformed RFC 9497 client state: {error}")
            }
            Self::EvaluationElement(error) => {
                write!(formatter, "Malformed RFC 9497 evaluation element: {error}")
            }
            Self::Finalize(error) => {
                write!(formatter, "RFC 9497 client finalization failed: {error}")
            }
        }
    }
}

fn require_element_length(value: &[u8], name: &'static str) -> Result<(), OprfError> {
    if value.len() != ELEMENT_LENGTH {
        return Err(OprfError::InvalidLength {
            name,
            length: value.len(),
        });
    }

    Ok(())
}

fn require_input_length(input_data: &[u8]) -> Result<(), OprfError> {
    if input_data.is_empty() {
        return Err(OprfError::InputEmpty);
    }

    if input_data.len() > MAX_INPUT_LENGTH {
        return Err(OprfError::InputTooLong(input_data.len()));
    }

    Ok(())
}

fn blind_inner(input_data: &[u8]) -> Result<(Vec<u8>, Vec<u8>), OprfError> {
    require_input_length(input_data)?;

    let blind_result =
        OprfClient::<Ristretto255>::blind(input_data, &mut OsRng).map_err(OprfError::Blind)?;

    Ok((
        blind_result.message.serialize().to_vec(),
        blind_result.state.serialize().to_vec(),
    ))
}

fn evaluate_inner(server_key: &[u8], blinded_element: &[u8]) -> Result<Vec<u8>, OprfError> {
    require_element_length(server_key, "RFC 9497 server key")?;
    require_element_length(blinded_element, "RFC 9497 blinded element")?;

    let server =
        OprfServer::<Ristretto255>::new_with_key(server_key).map_err(OprfError::ServerKey)?;

    let blinded_element = BlindedElement::<Ristretto255>::deserialize(blinded_element)
        .map_err(OprfError::BlindedElement)?;

    Ok(server.blind_evaluate(&blinded_element).serialize().to_vec())
}

fn finalize_inner(
    input_data: &[u8],
    client_state: &[u8],
    evaluated_element: &[u8],
) -> Result<Vec<u8>, OprfError> {
    require_input_length(input_data)?;
    require_element_length(client_state, "RFC 9497 client state")?;
    require_element_length(evaluated_element, "RFC 9497 evaluation element")?;

    let client =
        OprfClient::<Ristretto255>::deserialize(client_state).map_err(OprfError::ClientState)?;

    let evaluated_element = EvaluationElement::<Ristretto255>::deserialize(evaluated_element)
        .map_err(OprfError::EvaluationElement)?;

    client
        .finalize(input_data, &evaluated_element)
        .map(|output| output.to_vec())
        .map_err(OprfError::Finalize)
}

/// Client-side RFC 9497 blinding.
///
/// Input:
///  canonical serialized assertion bytes
///
/// Returns:
///  (blinded_element, client_state)
#[pyfunction]
fn blind(input_data: &[u8]) -> PyResult<(Vec<u8>, Vec<u8>)> {
    blind_inner(input_data).map_err(|error| PyValueError::new_err(error.to_string()))
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
    evaluate_inner(server_key, blinded_element)
        .map_err(|error| PyValueError::new_err(error.to_string()))
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
    finalize_inner(input_data, client_state, evaluated_element)
        .map_err(|error| PyValueError::new_err(error.to_string()))
}

#[pymodule]
fn verity_oprf(m: &Bound<'_, PyModule>) -> PyResult<()> {
    m.add_function(wrap_pyfunction!(blind, m)?)?;
    m.add_function(wrap_pyfunction!(evaluate, m)?)?;
    m.add_function(wrap_pyfunction!(finalize, m)?)?;

    Ok(())
}

#[cfg(test)]
mod fuzz;
