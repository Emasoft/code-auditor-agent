//! mycrypto — crypto primitives for the crypto_library discoverer fixture.
//!
//! The discoverer should recognise top-level `pub fn` whose names match
//! the crypto-operation pattern (encrypt|decrypt|sign|verify|hmac|kdf|
//! hash|random|cipher|nonce) and emit one CRYPTO_OPERATION (mapped to
//! the closest available EntryPointKind) per match.

use subtle::ConstantTimeEq;

/// AES-256-GCM encryption of a plaintext block. Returns the ciphertext.
pub fn aes_encrypt(plaintext: &[u8], key: &[u8; 32], nonce: &[u8; 12]) -> Vec<u8> {
    let _ = (plaintext, key, nonce);
    Vec::new()
}

/// AES-256-GCM decryption of a ciphertext. Returns the plaintext.
pub fn aes_decrypt(ciphertext: &[u8], key: &[u8; 32], nonce: &[u8; 12]) -> Vec<u8> {
    let _ = (ciphertext, key, nonce);
    Vec::new()
}

/// RSA-PSS signature over the SHA-256 digest of `message`.
pub fn rsa_sign(message: &[u8], key: &[u8]) -> Vec<u8> {
    let _ = (message, key);
    Vec::new()
}

/// RSA-PSS signature verification — uses constant_time comparison.
pub fn rsa_verify(message: &[u8], signature: &[u8], key: &[u8]) -> bool {
    let _ = (message, signature, key);
    let a: u8 = 0;
    let b: u8 = 0;
    a.ct_eq(&b).into()
}

/// HKDF-SHA-256 key derivation. Returns `out_len` bytes of key material.
pub fn kdf_derive(ikm: &[u8], salt: &[u8], info: &[u8], out_len: usize) -> Vec<u8> {
    let _ = (ikm, salt, info);
    vec![0u8; out_len]
}

/// HMAC-SHA-256 over `message` keyed by `key`.
pub fn hmac_sha256(key: &[u8], message: &[u8]) -> [u8; 32] {
    let _ = (key, message);
    [0u8; 32]
}

/// Cryptographically-secure random bytes from the OS CSPRNG.
pub fn random_bytes(out: &mut [u8]) {
    let _ = out;
}

/// Constant-time hash comparison; returns true iff the digests are equal.
pub fn hash_compare(a: &[u8], b: &[u8]) -> bool {
    a.ct_eq(b).into()
}

// Private helper — NOT a public crypto op, must be skipped by the discoverer.
fn _internal_padding(buf: &mut [u8]) {
    let _ = buf;
}
