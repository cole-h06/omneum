use std::fmt;

use pyo3::exceptions::PyValueError;
use pyo3::prelude::*;
use rand::rngs::OsRng;
use voprf::{
    BlindedElement, Error as VoprfError, EvaluationElement, Group, Proof, Ristretto255,
    VoprfClient, VoprfServer,
};

const ELEMENT_LENGTH: usize = 32;
const CLIENT_STATE_LENGTH: usize = 64;
const PROOF_LENGTH: usize = 64;
const OUTPUT_LENGTH: usize = 64;
const MAX_INPUT_LENGTH: usize = 65_534;

enum OprfError {
    InvalidLength {
        name: &'static str,
        expected: usize,
        length: usize,
    },
    InputEmpty,
    InputTooLong(usize),
    Blind(VoprfError),
    BlindIdentity(VoprfError),
    ServerKey(VoprfError),
    BlindedElement(VoprfError),
    ClientState(VoprfError),
    EvaluationElement(VoprfError),
    Proof(VoprfError),
    PublicKey(VoprfError),
    Finalize(VoprfError),
}

impl fmt::Display for OprfError {
    fn fmt(&self, formatter: &mut fmt::Formatter<'_>) -> fmt::Result {
        match self {
            Self::InvalidLength {
                name,
                expected,
                length,
            } => write!(
                formatter,
                "{name} must be {expected} bytes; received {length}"
            ),
            Self::InputEmpty => write!(formatter, "RFC 9497 private input must not be empty"),
            Self::InputTooLong(length) => write!(
                formatter,
                "RFC 9497 private input must be at most {MAX_INPUT_LENGTH} bytes; received {length}"
            ),
            Self::Blind(error) => {
                write!(formatter, "RFC 9497 VOPRF client blinding failed: {error}")
            }
            Self::BlindIdentity(error) => {
                write!(formatter, "RFC 9497 VOPRF client blinding failed: {error}")
            }
            Self::ServerKey(error) => {
                write!(formatter, "Invalid RFC 9497 VOPRF server key: {error}")
            }
            Self::BlindedElement(error) => {
                write!(
                    formatter,
                    "Malformed RFC 9497 VOPRF blinded element: {error}"
                )
            }
            Self::ClientState(error) => {
                write!(formatter, "Malformed RFC 9497 VOPRF client state: {error}")
            }
            Self::EvaluationElement(error) => {
                write!(
                    formatter,
                    "Malformed RFC 9497 VOPRF evaluation element: {error}"
                )
            }
            Self::Proof(error) => {
                write!(formatter, "Malformed RFC 9497 VOPRF proof: {error}")
            }
            Self::PublicKey(error) => {
                write!(formatter, "Malformed RFC 9497 VOPRF public key: {error}")
            }
            Self::Finalize(error) => {
                write!(
                    formatter,
                    "RFC 9497 VOPRF client finalization failed: {error}"
                )
            }
        }
    }
}

fn require_length(value: &[u8], name: &'static str, expected: usize) -> Result<(), OprfError> {
    if value.len() != expected {
        return Err(OprfError::InvalidLength {
            name,
            expected,
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
        VoprfClient::<Ristretto255>::blind(input_data, &mut OsRng).map_err(OprfError::Blind)?;
    let blinded_element = blind_result.message.serialize();

    validate_generated_blind(&blinded_element)?;

    Ok((
        blinded_element.to_vec(),
        blind_result.state.serialize().to_vec(),
    ))
}

fn validate_generated_blind(blinded_element: &[u8]) -> Result<(), OprfError> {
    BlindedElement::<Ristretto255>::deserialize(blinded_element)
        .map_err(OprfError::BlindIdentity)?;
    Ok(())
}

fn server_from_key(server_key: &[u8]) -> Result<VoprfServer<Ristretto255>, OprfError> {
    require_length(server_key, "RFC 9497 VOPRF server key", ELEMENT_LENGTH)?;
    VoprfServer::<Ristretto255>::new_with_key(server_key).map_err(OprfError::ServerKey)
}

fn derive_public_key_inner(server_key: &[u8]) -> Result<Vec<u8>, OprfError> {
    let server = server_from_key(server_key)?;

    Ok(
        <Ristretto255 as voprf::CipherSuite>::Group::serialize_elem(server.get_public_key())
            .to_vec(),
    )
}

fn validate_public_key_inner(server_public_key: &[u8]) -> Result<(), OprfError> {
    require_length(
        server_public_key,
        "RFC 9497 VOPRF public key",
        ELEMENT_LENGTH,
    )?;
    <Ristretto255 as voprf::CipherSuite>::Group::deserialize_elem(server_public_key)
        .map_err(OprfError::PublicKey)?;
    Ok(())
}

fn evaluate_inner(
    server_key: &[u8],
    blinded_element: &[u8],
) -> Result<(Vec<u8>, Vec<u8>), OprfError> {
    require_length(
        blinded_element,
        "RFC 9497 VOPRF blinded element",
        ELEMENT_LENGTH,
    )?;

    let server = server_from_key(server_key)?;
    let blinded_element = BlindedElement::<Ristretto255>::deserialize(blinded_element)
        .map_err(OprfError::BlindedElement)?;
    let result = server.blind_evaluate(&mut OsRng, &blinded_element);

    Ok((
        result.message.serialize().to_vec(),
        result.proof.serialize().to_vec(),
    ))
}

fn finalize_inner(
    input_data: &[u8],
    client_state: &[u8],
    evaluated_element: &[u8],
    proof: &[u8],
    server_public_key: &[u8],
) -> Result<Vec<u8>, OprfError> {
    require_input_length(input_data)?;
    require_length(
        client_state,
        "RFC 9497 VOPRF client state",
        CLIENT_STATE_LENGTH,
    )?;
    require_length(
        evaluated_element,
        "RFC 9497 VOPRF evaluation element",
        ELEMENT_LENGTH,
    )?;
    require_length(proof, "RFC 9497 VOPRF proof", PROOF_LENGTH)?;
    validate_public_key_inner(server_public_key)?;

    let client =
        VoprfClient::<Ristretto255>::deserialize(client_state).map_err(OprfError::ClientState)?;
    let evaluated_element = EvaluationElement::<Ristretto255>::deserialize(evaluated_element)
        .map_err(OprfError::EvaluationElement)?;
    let proof = Proof::<Ristretto255>::deserialize(proof).map_err(OprfError::Proof)?;
    let public_key =
        <Ristretto255 as voprf::CipherSuite>::Group::deserialize_elem(server_public_key)
            .map_err(OprfError::PublicKey)?;

    let output = client
        .finalize(input_data, &evaluated_element, &proof, public_key)
        .map_err(OprfError::Finalize)?
        .to_vec();

    require_length(&output, "RFC 9497 VOPRF output", OUTPUT_LENGTH)?;
    Ok(output)
}

#[pyfunction]
fn blind(input_data: &[u8]) -> PyResult<(Vec<u8>, Vec<u8>)> {
    blind_inner(input_data).map_err(|error| PyValueError::new_err(error.to_string()))
}

#[pyfunction]
fn derive_public_key(server_key: &[u8]) -> PyResult<Vec<u8>> {
    derive_public_key_inner(server_key).map_err(|error| PyValueError::new_err(error.to_string()))
}

#[pyfunction]
fn validate_public_key(server_public_key: &[u8]) -> PyResult<()> {
    validate_public_key_inner(server_public_key)
        .map_err(|error| PyValueError::new_err(error.to_string()))
}

#[pyfunction]
fn evaluate(server_key: &[u8], blinded_element: &[u8]) -> PyResult<(Vec<u8>, Vec<u8>)> {
    evaluate_inner(server_key, blinded_element)
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
fn verity_oprf(m: &Bound<'_, PyModule>) -> PyResult<()> {
    m.add_function(wrap_pyfunction!(blind, m)?)?;
    m.add_function(wrap_pyfunction!(derive_public_key, m)?)?;
    m.add_function(wrap_pyfunction!(validate_public_key, m)?)?;
    m.add_function(wrap_pyfunction!(evaluate, m)?)?;
    m.add_function(wrap_pyfunction!(finalize, m)?)?;

    Ok(())
}

#[cfg(test)]
mod fuzz;
