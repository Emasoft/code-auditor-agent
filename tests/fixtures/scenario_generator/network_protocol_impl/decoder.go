// fixture for network_protocol_impl — custom binary protocol decoder.
//
// The network_protocol_impl fingerprint requires the literal strings
// "parsePacket" and "PacketHeader" to appear in a *.go file. This file
// supplies both, plus encoder/decoder/handler functions for the
// discoverer to enumerate.
//
// Lives in package "protocol" (NOT "main") so the cli_go fingerprint
// (which requires `package main` in main.go) does not also match.

package protocol

import "encoding/binary"

// PacketHeader is the fixed-size prelude of every wire frame.
type PacketHeader struct {
	Magic   uint32
	Version uint32
	Length  uint32
	Type    uint32
}

// parsePacket splits a wire frame into header + payload.
func parsePacket(data []byte) (*PacketHeader, []byte, error) {
	if len(data) < 16 {
		return nil, nil, errShort
	}
	h := &PacketHeader{
		Magic:   binary.BigEndian.Uint32(data[0:4]),
		Version: binary.BigEndian.Uint32(data[4:8]),
		Length:  binary.BigEndian.Uint32(data[8:12]),
		Type:    binary.BigEndian.Uint32(data[12:16]),
	}
	return h, data[16:], nil
}

// HeaderEncode serialises a PacketHeader into the 16-byte wire form.
func HeaderEncode(h *PacketHeader, out []byte) {
	binary.BigEndian.PutUint32(out[0:4], h.Magic)
	binary.BigEndian.PutUint32(out[4:8], h.Version)
	binary.BigEndian.PutUint32(out[8:12], h.Length)
	binary.BigEndian.PutUint32(out[12:16], h.Type)
}

// HeaderDecode deserialises a 16-byte wire header in-place.
func HeaderDecode(in []byte) *PacketHeader {
	return &PacketHeader{
		Magic:   binary.BigEndian.Uint32(in[0:4]),
		Version: binary.BigEndian.Uint32(in[4:8]),
		Length:  binary.BigEndian.Uint32(in[8:12]),
		Type:    binary.BigEndian.Uint32(in[12:16]),
	}
}

// parseControlMessage validates and unpacks a CONTROL-type packet.
func parseControlMessage(payload []byte) (*ControlPacket, error) {
	if len(payload) < 8 {
		return nil, errShort
	}
	return &ControlPacket{
		Opcode: binary.BigEndian.Uint32(payload[0:4]),
		Length: binary.BigEndian.Uint32(payload[4:8]),
	}, nil
}

// handleDataPacket routes a DATA-type packet to its consumer.
func handleDataPacket(h *PacketHeader, payload []byte) error {
	_ = h
	_ = payload
	return nil
}

// PacketDispatch is the type-to-handler table consulted on every
// inbound frame.
var PacketDispatch = map[uint32]func(*PacketHeader, []byte) error{
	0x01: handleDataPacket,
}

type ControlPacket struct {
	Opcode uint32
	Length uint32
}

var errShort = stringError("packet too short")

type stringError string

func (e stringError) Error() string { return string(e) }
