/* fixture for os_baremetal
 *
 * High-level kernel entry that the bootloader (entry.s) jumps to.  The
 * os_baremetal discoverer picks up `kernel_main` as BOOT_PATH and any
 * function decorated with __attribute__((interrupt)) as ISR_VECTOR.
 */

void kernel_main(void)
{
	for (;;) {
		/* idle */
	}
}

__attribute__((interrupt))
void page_fault_isr(void *frame)
{
	(void)frame;
}

void timer_isr(void)
{
	/* Suffix-based ISR detection — the function name ends in `_isr`
	 * so the discoverer recognises it as ISR_VECTOR even without
	 * the __attribute__((interrupt)) marker. */
}
