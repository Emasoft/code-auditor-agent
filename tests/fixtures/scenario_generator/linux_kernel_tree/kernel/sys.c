// SPDX-License-Identifier: GPL-2.0
// Fixture: a kernel-tree syscall implementation using the SYSCALL_DEFINE
// macros that the linux_kernel_tree discoverer recognises.

#include <linux/kernel.h>
#include <linux/syscalls.h>

SYSCALL_DEFINE1(fixture_getpid, int, dummy)
{
	(void)dummy;
	return 1;
}

SYSCALL_DEFINE3(fixture_write, unsigned int, fd, const char __user *, buf, size_t, count)
{
	(void)fd;
	(void)buf;
	return (long)count;
}
