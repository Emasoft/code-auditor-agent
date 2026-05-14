/* fixture for os_baremetal
 *
 * A minimal linker script for a hobby/custom OS kernel.  Deliberately
 * does NOT contain the substrings "MEMORY", ".text", or ".bss" that
 * the firmware_baremetal fingerprint requires — so this fixture is
 * detected as os_baremetal, not firmware_baremetal.
 */

ENTRY(_start)

SECTIONS {
	. = 0x100000;
	code : { *(code) }
	rodata : { *(rodata) }
	data : { *(data) }
	end_marker = .;
}
