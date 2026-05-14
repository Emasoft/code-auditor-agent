/*-
 * fixture for bsd_kernel
 * A second BSD source unit using DECLARE_MODULE — the canonical
 * subsystem-style registration distinct from DEV_MODULE.
 */

#include <sys/param.h>
#include <sys/module.h>
#include <sys/kernel.h>
#include <sys/systm.h>

static int
bar_modevent(module_t mod, int what, void *arg)
{
	(void)mod;
	(void)arg;
	(void)what;
	return 0;
}

static moduledata_t bar_mod = {
	"bar",
	bar_modevent,
	NULL
};

DECLARE_MODULE(bar, bar_mod, SI_SUB_DRIVERS, SI_ORDER_MIDDLE);
MODULE_VERSION(bar, 2);
