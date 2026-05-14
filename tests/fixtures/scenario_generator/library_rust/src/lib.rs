//! myrustlib — fixture crate for the library_rust discoverer.
//!
//! The discoverer should pick up `pub fn`, `pub struct`, `pub trait`,
//! `pub enum` at module scope and skip anything inside `impl` blocks
//! and any `pub(crate)` / `pub(super)` visibility.

/// Trim whitespace from a byte slice. Public crate-API.
pub fn trim_bytes(input: &[u8]) -> Vec<u8> {
    input.iter().copied().filter(|b| !b.is_ascii_whitespace()).collect()
}

/// A simple struct with a name and a numeric weight.
pub struct Widget {
    pub name: String,
    pub weight: u32,
}

impl Widget {
    /// Constructor — discoverer must NOT emit this (it's inside impl).
    pub fn new(name: &str, weight: u32) -> Self {
        Self { name: name.to_owned(), weight }
    }
}

/// Public trait for things that can be greeted.
pub trait Greet {
    fn greet(&self) -> String;
}

/// Public enum used as a result discriminator.
pub enum Outcome {
    Success,
    Failure,
}

// Crate-internal helper — must NOT appear as a library export.
pub(crate) fn _crate_only_helper() -> u32 {
    0
}

fn private_module_fn() -> u32 {
    1
}
