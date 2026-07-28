use bolero::check;

use super::{
    ELEMENT_LENGTH, MAX_INPUT_LENGTH, OprfError, blind_inner, evaluate_inner, finalize_inner,
    require_input_length,
};

const BLINDED_ELEMENT: [u8; ELEMENT_LENGTH] = [
    0x60, 0x9a, 0x0a, 0xe6, 0x8c, 0x15, 0xa3, 0xcf, 0x69, 0x03, 0x76, 0x64, 0x61, 0x30, 0x7e, 0x5c,
    0x8b, 0xb2, 0xf9, 0x5e, 0x7e, 0x65, 0x50, 0xe1, 0xff, 0xa2, 0xdc, 0x99, 0xe4, 0x12, 0x80, 0x3c,
];
const CLIENT_STATE: [u8; ELEMENT_LENGTH] = [
    0x64, 0xd3, 0x7a, 0xed, 0x22, 0xa2, 0x7f, 0x51, 0x91, 0xde, 0x1c, 0x1d, 0x69, 0xfa, 0xdb, 0x89,
    0x9d, 0x88, 0x62, 0xb5, 0x8e, 0xb4, 0x22, 0x00, 0x29, 0xe0, 0x36, 0xec, 0x4c, 0x1f, 0x67, 0x06,
];
const EVALUATED_ELEMENT: [u8; ELEMENT_LENGTH] = [
    0x7e, 0xc6, 0x57, 0x8a, 0xe5, 0x12, 0x09, 0x58, 0xeb, 0x2d, 0xb1, 0x74, 0x57, 0x58, 0xff, 0x37,
    0x9e, 0x77, 0xcb, 0x64, 0xfe, 0x77, 0xb0, 0xb2, 0xd8, 0xcc, 0x91, 0x7e, 0xa0, 0x86, 0x9c, 0x7e,
];
const SERVER_KEY: [u8; ELEMENT_LENGTH] = [
    0x5e, 0xbc, 0xea, 0x5e, 0xe3, 0x70, 0x23, 0xcc, 0xb9, 0xfc, 0x2d, 0x20, 0x19, 0xf9, 0xd7, 0x73,
    0x7b, 0xe8, 0x55, 0x91, 0xae, 0x86, 0x52, 0xff, 0xa9, 0xef, 0x0f, 0x4d, 0x37, 0x06, 0x3b, 0x0e,
];

#[test]
fn empty_input() {
    assert!(matches!(blind_inner(&[]), Err(OprfError::InputEmpty)));
    assert!(matches!(
        finalize_inner(&[], &CLIENT_STATE, &EVALUATED_ELEMENT),
        Err(OprfError::InputEmpty)
    ));
}

#[test]
fn fuzz_evaluate() {
    check!().for_each(|data: &[u8]| {
        let (selector, value) = data.split_first().unwrap_or((&0, &[]));
        let value = &value[..value.len().min(64)];
        let result = if selector % 2 == 0 {
            evaluate_inner(&SERVER_KEY, value)
        } else {
            evaluate_inner(value, &BLINDED_ELEMENT)
        };

        if let Ok(evaluated_element) = result {
            assert_eq!(evaluated_element.len(), ELEMENT_LENGTH);
        }
    });
}

#[test]
fn fuzz_finalize() {
    check!().for_each(|data: &[u8]| {
        let (selector, value) = data.split_first().unwrap_or((&0, &[]));
        let value = &value[..value.len().min(64)];
        let result = if selector % 2 == 0 {
            finalize_inner(&[0], value, &EVALUATED_ELEMENT)
        } else {
            finalize_inner(&[0], &CLIENT_STATE, value)
        };

        if let Ok(output) = result {
            assert_eq!(output.len(), 64);
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
