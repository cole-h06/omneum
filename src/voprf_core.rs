use std::fmt;
use std::io::{self, Read};

use rand::rngs::OsRng;
use voprf::{
    BlindedElement, Error as VoprfError, EvaluationElement, Group, Proof, Ristretto255,
    VoprfClient, VoprfServer,
};
use zeroize::Zeroizing;

pub(crate) const ELEMENT_LENGTH: usize = 32;
pub(crate) const CLIENT_STATE_LENGTH: usize = 64;
pub(crate) const PROOF_LENGTH: usize = 64;
pub(crate) const OUTPUT_LENGTH: usize = 64;
pub(crate) const MAX_INPUT_LENGTH: usize = 65_534;

pub(crate) enum OprfError {
    InvalidLength {
        name: &'static str,
        expected: usize,
        length: usize,
    },
    InputEmpty,
    InputTooLong(usize),
    Blind(VoprfError),
    BlindIdentity(VoprfError),
    KeyFile,
    KeyFileLength,
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
            Self::KeyFile => write!(formatter, "Unable to read VOPRF private key file"),
            Self::KeyFileLength => {
                write!(
                    formatter,
                    "VOPRF private key file must contain exactly 32 bytes"
                )
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

pub(crate) fn require_length(
    value: &[u8],
    name: &'static str,
    expected: usize,
) -> Result<(), OprfError> {
    if value.len() != expected {
        return Err(OprfError::InvalidLength {
            name,
            expected,
            length: value.len(),
        });
    }

    Ok(())
}

pub(crate) fn require_input_length(input_data: &[u8]) -> Result<(), OprfError> {
    if input_data.is_empty() {
        return Err(OprfError::InputEmpty);
    }

    if input_data.len() > MAX_INPUT_LENGTH {
        return Err(OprfError::InputTooLong(input_data.len()));
    }

    Ok(())
}

pub(crate) fn blind_inner(input_data: &[u8]) -> Result<(Vec<u8>, Vec<u8>), OprfError> {
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

pub(crate) fn validate_generated_blind(blinded_element: &[u8]) -> Result<(), OprfError> {
    BlindedElement::<Ristretto255>::deserialize(blinded_element)
        .map_err(OprfError::BlindIdentity)?;
    Ok(())
}

pub(crate) fn server_from_key(server_key: &[u8]) -> Result<VoprfServer<Ristretto255>, OprfError> {
    require_length(server_key, "RFC 9497 VOPRF server key", ELEMENT_LENGTH)?;
    VoprfServer::<Ristretto255>::new_with_key(server_key).map_err(OprfError::ServerKey)
}

pub(crate) fn server_from_reader(
    mut reader: impl Read,
) -> Result<VoprfServer<Ristretto255>, OprfError> {
    let mut server_key = Zeroizing::new([0_u8; ELEMENT_LENGTH + 1]);
    reader
        .read_exact(&mut server_key[..ELEMENT_LENGTH])
        .map_err(|error| match error.kind() {
            io::ErrorKind::UnexpectedEof => OprfError::KeyFileLength,
            _ => OprfError::KeyFile,
        })?;

    match reader.read_exact(&mut server_key[ELEMENT_LENGTH..]) {
        Ok(()) => return Err(OprfError::KeyFileLength),
        Err(error) if error.kind() == io::ErrorKind::UnexpectedEof => {}
        Err(_) => return Err(OprfError::KeyFile),
    }

    server_from_key(&server_key[..ELEMENT_LENGTH])
}

#[cfg(test)]
pub(crate) fn derive_public_key_inner(server_key: &[u8]) -> Result<Vec<u8>, OprfError> {
    let server = server_from_key(server_key)?;

    Ok(
        <Ristretto255 as voprf::CipherSuite>::Group::serialize_elem(server.get_public_key())
            .to_vec(),
    )
}

pub(crate) fn validate_public_key_inner(server_public_key: &[u8]) -> Result<(), OprfError> {
    require_length(
        server_public_key,
        "RFC 9497 VOPRF public key",
        ELEMENT_LENGTH,
    )?;
    <Ristretto255 as voprf::CipherSuite>::Group::deserialize_elem(server_public_key)
        .map_err(OprfError::PublicKey)?;
    Ok(())
}

pub(crate) fn evaluate_with_server(
    server: &VoprfServer<Ristretto255>,
    blinded_element: &[u8],
) -> Result<(Vec<u8>, Vec<u8>), OprfError> {
    require_length(
        blinded_element,
        "RFC 9497 VOPRF blinded element",
        ELEMENT_LENGTH,
    )?;

    let blinded_element = BlindedElement::<Ristretto255>::deserialize(blinded_element)
        .map_err(OprfError::BlindedElement)?;
    let result = server.blind_evaluate(&mut OsRng, &blinded_element);

    Ok((
        result.message.serialize().to_vec(),
        result.proof.serialize().to_vec(),
    ))
}

#[cfg(test)]
pub(crate) fn evaluate_inner(
    server_key: &[u8],
    blinded_element: &[u8],
) -> Result<(Vec<u8>, Vec<u8>), OprfError> {
    let server = server_from_key(server_key)?;
    evaluate_with_server(&server, blinded_element)
}

pub(crate) fn finalize_inner(
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
