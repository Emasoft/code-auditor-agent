// fixture for network_protocol_impl — Rust-language stub.
//
// Present so the network_protocol_impl fingerprint (which requires
// the strings parse_packet AND PacketHeader to appear in a *.rs file)
// can fire. The encoder/decoder/handler functions below are also
// picked up by the network_protocol_impl discoverer.
//
// Lives standalone (no Cargo.toml in this fixture) so neither
// library_rust ([lib]) nor cli_rust ([[bin]]) can also match.

/// PacketHeader — wire-format prelude.
pub struct PacketHeader {
    pub magic: u32,
    pub version: u32,
    pub length: u32,
}

/// parse_packet — also matches the network_protocol_impl fingerprint string.
pub fn parse_packet(data: &[u8]) -> Option<PacketHeader> {
    if data.len() < 12 {
        return None;
    }
    Some(PacketHeader {
        magic: u32::from_be_bytes([data[0], data[1], data[2], data[3]]),
        version: u32::from_be_bytes([data[4], data[5], data[6], data[7]]),
        length: u32::from_be_bytes([data[8], data[9], data[10], data[11]]),
    })
}

/// decode_header — discoverer entry point (matches decode_*).
pub fn decode_header(data: &[u8]) -> Option<PacketHeader> {
    parse_packet(data)
}

/// encode_header — discoverer entry point (matches encode_*).
pub fn encode_header(h: &PacketHeader, out: &mut [u8]) {
    out[0..4].copy_from_slice(&h.magic.to_be_bytes());
    out[4..8].copy_from_slice(&h.version.to_be_bytes());
    out[8..12].copy_from_slice(&h.length.to_be_bytes());
}

/// handle_data_packet — discoverer entry point (matches handle_*_packet).
pub fn handle_data_packet(h: &PacketHeader, payload: &[u8]) -> bool {
    let _ = h;
    let _ = payload;
    true
}
