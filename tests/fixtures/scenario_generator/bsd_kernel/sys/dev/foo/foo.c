/*-
 * fixture for bsd_kernel
 * A minimal FreeBSD character-device kernel module exercising the
 * macros that the bsd_kernel discoverer recognises:
 *   DEV_MODULE / MODULE_DEPEND / MODULE_VERSION / SYSCTL_INT
 */

#include <sys/param.h>
#include <sys/module.h>
#include <sys/kernel.h>
#include <sys/sysctl.h>
#include <sys/systm.h>

/* Module event handler — invoked by the kernel on load/unload. */
static int
foo_modevent(module_t mod, int what, void *arg)
{
	(void)mod;
	(void)arg;
	switch (what) {
	case MOD_LOAD:
		return 0;
	case MOD_UNLOAD:
		return 0;
	default:
		return EOPNOTSUPP;
	}
}

DEV_MODULE(foo, foo_modevent, NULL);
MODULE_VERSION(foo, 1);
MODULE_DEPEND(foo, kernel, 1, 1, 1);
MODULE_DEPEND(foo, usb, 1, 1, 1);

static int foo_debug = 0;
SYSCTL_INT(_debug, OID_AUTO, foo_debug, CTLFLAG_RW, &foo_debug, 0,
    "Enable foo debug logging");
