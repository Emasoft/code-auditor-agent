// SPDX-License-Identifier: GPL-2.0
// Fixture: a minimal Linux kernel module exercising every entry-point
// kind that the linux_kernel_module discoverer recognises.

#include <linux/module.h>
#include <linux/fs.h>
#include <linux/uaccess.h>
#include <linux/init.h>

MODULE_LICENSE("GPL");
MODULE_AUTHOR("Code Auditor Agent fixture");
MODULE_DESCRIPTION("Linux kernel module discoverer test fixture");

// Helper exported to other modules — should be picked up as IPC_HANDLER.
int myhw_helper(void)
{
    return 0;
}
EXPORT_SYMBOL(myhw_helper);

// ioctl handler — should be picked up as IOCTL_HANDLER via .unlocked_ioctl
// member of the fops struct below.
static long myhw_ioctl(struct file *f, unsigned int cmd, unsigned long arg)
{
    (void)f;
    (void)cmd;
    (void)arg;
    return 0;
}

// read / write — should be picked up as SYSCALL_HANDLER entries with the
// appropriate `.op` metadata.
static ssize_t myhw_read(struct file *f, char __user *buf, size_t len, loff_t *off)
{
    (void)f;
    (void)buf;
    (void)len;
    (void)off;
    return 0;
}

static ssize_t myhw_write(struct file *f, const char __user *buf, size_t len, loff_t *off)
{
    (void)f;
    (void)buf;
    (void)len;
    (void)off;
    return (ssize_t)len;
}

// file_operations struct — the discoverer scans inside for `.member = fn,`
// pairs and emits one entry point per recognised member.
static struct file_operations myhw_fops = {
    .owner = THIS_MODULE,
    .unlocked_ioctl = myhw_ioctl,
    .read = myhw_read,
    .write = myhw_write,
};

// module_init / module_exit — registered last so the line numbers in the
// golden are stable and don't depend on the file header length.
static int __init myhw_init(void)
{
    (void)myhw_fops;
    return 0;
}

static void __exit myhw_exit(void)
{
}

module_init(myhw_init);
module_exit(myhw_exit);
