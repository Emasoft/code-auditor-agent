// SPDX-License-Identifier: GPL-2.0
// Fixture: an arch-specific setup file using staged initcalls — the
// linux_kernel_tree discoverer treats these as BOOT_PATH entries.

#include <linux/init.h>
#include <linux/kernel.h>

static int __init fixture_early_setup(void)
{
	return 0;
}
early_initcall(fixture_early_setup);

static int __init fixture_arch_setup(void)
{
	return 0;
}
arch_initcall(fixture_arch_setup);

static int __init fixture_late_setup(void)
{
	return 0;
}
late_initcall(fixture_late_setup);
