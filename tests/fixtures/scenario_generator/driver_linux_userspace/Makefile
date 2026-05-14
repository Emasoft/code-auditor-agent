# fixture for driver_linux_userspace
# Tiny Makefile shipped with the userspace USB driver. Triggers the
# library_c fingerprint as a side effect (the *.c files contain
# free-standing function definitions), but the type-detection
# registry returns BOTH types — `driver_linux_userspace` is the one
# the regression test checks for.
CC      ?= cc
CFLAGS  ?= -Wall -Wextra -O2 -std=c11
LDLIBS  := -lusb-1.0

driver: driver.c
	$(CC) $(CFLAGS) -o $@ $< $(LDLIBS)

clean:
	rm -f driver

.PHONY: clean
