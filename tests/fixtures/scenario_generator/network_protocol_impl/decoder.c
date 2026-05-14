/* fixture for network_protocol_impl — C-language stub.
 *
 * Present so the network_protocol_impl fingerprint, which requires a
 * .c AND a .rs AND a .go file to all match magic strings, can fire.
 * The compiled code is irrelevant — only the strings parse_packet,
 * encode_packet, and packet_header in the source are load-bearing
 * for detection.
 *
 * The discoverer also finds protocol_encode/protocol_decode and any
 * dispatch table here.
 */

/* packet_header — wire-format prelude struct. */
struct packet_header {
    unsigned int magic;
    unsigned int length;
};

/* protocol_decode — discoverer entry point (matches *_decode). */
int protocol_decode(const unsigned char *buf, unsigned int len)
{
    (void)buf;
    return (int)len;
}

/* protocol_encode — discoverer entry point (matches *_encode). */
int protocol_encode(unsigned char *out, const struct packet_header *h)
{
    out[0] = (unsigned char)h->magic;
    return 1;
}

/* parse_packet — also matches the network_protocol_impl fingerprint string. */
int parse_packet(const unsigned char *buf, unsigned int len)
{
    return protocol_decode(buf, len);
}

/* encode_packet — also matches the network_protocol_impl fingerprint string. */
int encode_packet(unsigned char *out, const struct packet_header *h)
{
    return protocol_encode(out, h);
}
