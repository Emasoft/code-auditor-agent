#include "mylib.h"

int mylib_strlen(const char *s) {
    int n = 0;
    while (s && s[n] != '\0') {
        n++;
    }
    return n;
}

void mylib_lower(char *buf, size_t n) {
    size_t i;
    for (i = 0; i < n; i++) {
        if (buf[i] >= 'A' && buf[i] <= 'Z') {
            buf[i] = (char)(buf[i] + ('a' - 'A'));
        }
    }
}

unsigned long mylib_checksum(const unsigned char *data, size_t len) {
    unsigned long acc = 0UL;
    size_t i;
    for (i = 0; i < len; i++) {
        acc = (acc * 33UL) + (unsigned long)data[i];
    }
    return acc;
}

/* File-static helper — NOT part of the public API. Header doesn't
 * declare it, so the discoverer must not emit it. */
static int internal_helper(int x) {
    return x * 2;
}
