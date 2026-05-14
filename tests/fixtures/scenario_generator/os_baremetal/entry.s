/* fixture for os_baremetal
 *
 * Hand-rolled bootloader stub that the linker.ld script enters at
 * _start. The os_baremetal discoverer recognises `_start:` as a
 * BOOT_PATH and `*_irq:` labels as ISR_VECTOR.
 *
 * Deliberately named `entry.s` (not `boot.s` / `boot.S` / `startup.S`)
 * so the firmware_baremetal fingerprint never matches this fixture on
 * case-insensitive filesystems (APFS, NTFS).
 */

.section code

.global _start
_start:
	mov $0x7c00, %esp
	jmp kernel_main

.global timer_irq
timer_irq:
	iret

.global keyboard_irq
keyboard_irq:
	iret
