# lib.rs

- **Source file:** `/uploads/code_bundle_30/rust/lib.rs`
- **Language:** Rust
- **Purpose:** Provides a small reusable predicate for checking integer parity.
- **Key functions/classes:** `pub fn is_even(value: i32) -> bool`.
- **Inputs:** A signed 32-bit integer.
- **Outputs:** Returns `true` when the value is divisible by 2, otherwise `false`.
- **Notable implementation details:** The function is public for library consumers and uses the remainder operator `%`.
