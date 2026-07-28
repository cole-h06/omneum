use bolero::check;

use super::{
    CLIENT_STATE_LENGTH, ELEMENT_LENGTH, MAX_INPUT_LENGTH, OUTPUT_LENGTH, OprfError, blind_inner,
    derive_public_key_inner, evaluate_inner, finalize_inner, require_input_length,
    validate_generated_blind,
};

const SERVER_KEY: [u8; ELEMENT_LENGTH] = [
    1, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0,
];

fn valid_round() -> (Vec<u8>, Vec<u8>, Vec<u8>, Vec<u8>) {
    let Ok((blinded_element, client_state)) = blind_inner(&[1]) else {
        panic!("valid blind failed");
    };
    let Ok((evaluated_element, proof)) = evaluate_inner(&SERVER_KEY, &blinded_element) else {
        panic!("valid evaluation failed");
    };
    (client_state, evaluated_element, proof, blinded_element)
}

fn decode(value: &str) -> Vec<u8> {
    let decoded = value
        .as_bytes()
        .chunks_exact(2)
        .map(|digits| {
            let digits = std::str::from_utf8(digits).map_err(|_| ())?;
            u8::from_str_radix(digits, 16).map_err(|_| ())
        })
        .collect::<Result<Vec<_>, _>>();
    let Ok(decoded) = decoded else {
        panic!("invalid test vector");
    };
    decoded
}

#[test]
fn empty_input() {
    let (client_state, evaluated_element, proof, _) = valid_round();
    let Ok(public_key) = derive_public_key_inner(&SERVER_KEY) else {
        panic!("valid public key failed");
    };

    assert!(matches!(blind_inner(&[]), Err(OprfError::InputEmpty)));
    assert!(matches!(
        finalize_inner(&[], &client_state, &evaluated_element, &proof, &public_key,),
        Err(OprfError::InputEmpty)
    ));
}

#[test]
fn message_shapes() {
    let (client_state, evaluated_element, proof, blinded_element) = valid_round();
    let Ok(public_key) = derive_public_key_inner(&SERVER_KEY) else {
        panic!("valid public key failed");
    };
    let Ok(output) = finalize_inner(&[1], &client_state, &evaluated_element, &proof, &public_key)
    else {
        panic!("valid finalization failed");
    };

    assert_eq!(blinded_element.len(), ELEMENT_LENGTH);
    assert_eq!(client_state.len(), CLIENT_STATE_LENGTH);
    assert_eq!(evaluated_element.len(), ELEMENT_LENGTH);
    assert_eq!(proof.len(), 64);
    assert_eq!(public_key.len(), ELEMENT_LENGTH);
    assert_eq!(output.len(), OUTPUT_LENGTH);
}

#[test]
fn generated_blind_guard() {
    assert!(validate_generated_blind(&[0; ELEMENT_LENGTH]).is_err());

    let (_, _, _, blinded_element) = valid_round();
    assert!(validate_generated_blind(&blinded_element).is_ok());
}

#[test]
fn rfc_9497_vector() {
    let server_key = decode("e6f73f344b79b379f1a0dd37e07ff62e38d9f71345ce62ae3a9bc60b04ccd909");
    let public_key = decode("c803e2cc6b05fc15064549b5920659ca4a77b2cca6f04f6b357009335476ad4e");
    let blind = decode("64d37aed22a27f5191de1c1d69fadb899d8862b58eb4220029e036ec4c1f6706");
    let blinded_element =
        decode("863f330cc1a1259ed5a5998a23acfd37fb4351a793a5b3c090b642ddc439b945");
    let evaluated_element =
        decode("aa8fa048764d5623868679402ff6108d2521884fa138cd7f9c7669a9a014267e");
    let proof = decode(
        "ddef93772692e535d1a53903db24367355cc2cc78de93b3be5a8ffcc6985dd06\
         6d4346421d17bf5117a2a1ff0fcb2a759f58a539dfbe857a40bce4cf49ec600d",
    );
    let output = decode(
        "b58cfbe118e0cb94d79b5fd6a6dafb98764dff49c14e1770b566e42402da1a7d\
         a4d8527693914139caee5bd03903af43a491351d23b430948dd50cde10d32b3c",
    );
    let client_state = [blind, blinded_element.clone()].concat();

    assert_eq!(
        derive_public_key_inner(&server_key).ok(),
        Some(public_key.clone())
    );
    let Ok((generated_element, generated_proof)) = evaluate_inner(&server_key, &blinded_element)
    else {
        panic!("vector evaluation failed");
    };
    assert_eq!(generated_element, evaluated_element);
    assert_eq!(
        finalize_inner(
            &[0],
            &client_state,
            &generated_element,
            &generated_proof,
            &public_key,
        )
        .ok(),
        Some(output.clone())
    );
    assert_eq!(
        finalize_inner(&[0], &client_state, &evaluated_element, &proof, &public_key,).ok(),
        Some(output)
    );
}

#[test]
fn fuzz_evaluate() {
    check!().for_each(|data: &[u8]| {
        let (_, _, _, blinded_element) = valid_round();
        let (selector, value) = data.split_first().unwrap_or((&0, &[]));
        let value = &value[..value.len().min(64)];
        let result = if selector % 2 == 0 {
            evaluate_inner(&SERVER_KEY, value)
        } else {
            evaluate_inner(value, &blinded_element)
        };

        if let Ok((evaluated_element, proof)) = result {
            assert_eq!(evaluated_element.len(), ELEMENT_LENGTH);
            assert_eq!(proof.len(), 64);
        }
    });
}

#[test]
fn fuzz_finalize() {
    check!().for_each(|data: &[u8]| {
        let (client_state, evaluated_element, proof, _) = valid_round();
        let Ok(public_key) = derive_public_key_inner(&SERVER_KEY) else {
            panic!("valid public key failed");
        };
        let (selector, value) = data.split_first().unwrap_or((&0, &[]));
        let value = &value[..value.len().min(64)];
        let result = match selector % 4 {
            0 => finalize_inner(&[1], value, &evaluated_element, &proof, &public_key),
            1 => finalize_inner(&[1], &client_state, value, &proof, &public_key),
            2 => finalize_inner(&[1], &client_state, &evaluated_element, value, &public_key),
            _ => finalize_inner(&[1], &client_state, &evaluated_element, &proof, value),
        };

        if let Ok(output) = result {
            assert_eq!(output.len(), OUTPUT_LENGTH);
        }
    });
}

#[test]
fn fuzz_input_length() {
    check!().for_each(|data: &[u8]| {
        let selector = data.first().copied().unwrap_or_default() % 7;
        let length = match selector {
            0 => 0,
            1 => 1,
            2 => MAX_INPUT_LENGTH - 1,
            3 => MAX_INPUT_LENGTH,
            4 => MAX_INPUT_LENGTH + 1,
            5 => MAX_INPUT_LENGTH + 2,
            _ => {
                let low = data.get(1).copied().unwrap_or_default();
                let high = data.get(2).copied().unwrap_or_default();
                usize::from(u16::from_le_bytes([low, high]))
            }
        };
        let input_data = vec![0; length.min(65_536)];

        assert_eq!(
            require_input_length(&input_data).is_ok(),
            !input_data.is_empty() && input_data.len() <= MAX_INPUT_LENGTH
        );
    });
}
