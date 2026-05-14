/* fixture for driver_linux_userspace
 *
 * Tiny userspace USB driver shaped after a real libusb client. The
 * discoverer extracts:
 *   - the libusb_init() / libusb_open_device_with_vid_pid() lifecycle
 *     hooks as EVENT_LISTENER entry points;
 *   - each ioctl(fd, REQ, ...) call site as an IOCTL_HANDLER;
 *   - main() as a MAIN_FUNCTION (the driver's boot path).
 *
 * The actual driver logic is stub-only — we never run this code, we
 * only parse it for entry-point discovery.
 */

#include <stdio.h>
#include <stdlib.h>
#include <sys/ioctl.h>
#include <libusb-1.0/libusb.h>

#define DEV_CONFIGURE _IOW('U', 1, int)
#define DEV_READ_STATUS _IOR('U', 2, int)

static int do_configure(int fd, int mode)
{
    /* Userspace configure path — issues a custom IOCTL into the kernel. */
    return ioctl(fd, DEV_CONFIGURE, &mode);
}

static int do_read_status(int fd, int *status_out)
{
    /* Userspace status-read path — issues a read-status IOCTL. */
    return ioctl(fd, DEV_READ_STATUS, status_out);
}

int main(int argc, char **argv)
{
    libusb_context *ctx = NULL;
    int rc = libusb_init(&ctx);
    if (rc != 0) {
        fprintf(stderr, "libusb_init failed: %d\n", rc);
        return 1;
    }

    libusb_device_handle *handle =
        libusb_open_device_with_vid_pid(ctx, 0x1234, 0x5678);
    if (!handle) {
        fprintf(stderr, "device not found\n");
        libusb_exit(ctx);
        return 2;
    }

    int fd = atoi(argv[1]);
    if (do_configure(fd, 1) < 0) {
        perror("configure");
    }
    int status = 0;
    if (do_read_status(fd, &status) < 0) {
        perror("read_status");
    }
    printf("status=%d\n", status);

    libusb_close(handle);
    libusb_exit(ctx);
    return 0;
}
