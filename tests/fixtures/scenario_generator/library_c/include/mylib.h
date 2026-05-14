#ifndef MYLIB_H
#define MYLIB_H

#include <stddef.h>

/**
 * Compute the length of a NUL-terminated string.
 *
 * Public API of mylibc. Returns the number of bytes before the
 * first NUL.
 */
int mylib_strlen(const char *s);

/**
 * Lower-case a byte buffer in place.
 *
 * The buffer must be writable and `n` bytes long.
 */
void mylib_lower(char *buf, size_t n);

/**
 * Compute a tiny additive checksum over a buffer.
 */
unsigned long mylib_checksum(const unsigned char *data, size_t len);

#endif /* MYLIB_H */
