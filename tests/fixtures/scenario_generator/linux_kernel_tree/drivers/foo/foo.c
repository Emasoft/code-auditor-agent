// SPDX-License-Identifier: GPL-2.0
// Fixture: an in-tree driver that ships module_init/exit + an exported
// helper. The linux_kernel_tree discoverer picks these up.

#include <linux/module.h>
#include <linux/init.h>

MODULE_LICENSE("GPL");
MODULE_DESCRIPTION("Linux kernel tree discoverer test fixture driver");

int foo_func(int x)
{
	return x + 1;
}
EXPORT_SYMBOL(foo_func);

static int __init foo_init(void)
{
	return 0;
}

static void __exit foo_exit(void)
{
}

module_init(foo_init);
module_exit(foo_exit);
