// fixture for windows_kernel_driver
// Minimal Windows WDM kernel-mode driver exercising every entry-point
// kind that the windows_kernel_driver discoverer recognises.

#include <ntddk.h>

// Forward declaration of an IO completion routine — the discoverer
// picks this up as EVENT_LISTENER from its IO_COMPLETION_ROUTINE
// typedef-style declaration.
IO_COMPLETION_ROUTINE FooIoCompletion;

// IRP dispatch handlers — forward declarations.
NTSTATUS FooCreate(PDEVICE_OBJECT DeviceObject, PIRP Irp);
NTSTATUS FooClose(PDEVICE_OBJECT DeviceObject, PIRP Irp);
NTSTATUS FooDispatchRead(PDEVICE_OBJECT DeviceObject, PIRP Irp);
NTSTATUS FooDispatchWrite(PDEVICE_OBJECT DeviceObject, PIRP Irp);
NTSTATUS FooDispatchIoctl(PDEVICE_OBJECT DeviceObject, PIRP Irp);

// DriverEntry — the driver's load-time entry point. The discoverer
// emits this as BOOT_PATH.
NTSTATUS DriverEntry(PDRIVER_OBJECT DriverObject, PUNICODE_STRING RegistryPath)
{
    UNREFERENCED_PARAMETER(RegistryPath);

    // Wire up the IRP major-function dispatch table — each assignment
    // is picked up as a separate entry point (IOCTL_HANDLER for
    // DEVICE_CONTROL, SYSCALL_HANDLER for READ/WRITE/CREATE/CLOSE,
    // IPC_HANDLER for everything else).
    DriverObject->MajorFunction[IRP_MJ_CREATE] = FooCreate;
    DriverObject->MajorFunction[IRP_MJ_CLOSE] = FooClose;
    DriverObject->MajorFunction[IRP_MJ_READ] = FooDispatchRead;
    DriverObject->MajorFunction[IRP_MJ_WRITE] = FooDispatchWrite;
    DriverObject->MajorFunction[IRP_MJ_DEVICE_CONTROL] = FooDispatchIoctl;

    return STATUS_SUCCESS;
}

NTSTATUS FooCreate(PDEVICE_OBJECT DeviceObject, PIRP Irp)
{
    UNREFERENCED_PARAMETER(DeviceObject);
    Irp->IoStatus.Status = STATUS_SUCCESS;
    Irp->IoStatus.Information = 0;
    IoCompleteRequest(Irp, IO_NO_INCREMENT);
    return STATUS_SUCCESS;
}

NTSTATUS FooClose(PDEVICE_OBJECT DeviceObject, PIRP Irp)
{
    UNREFERENCED_PARAMETER(DeviceObject);
    Irp->IoStatus.Status = STATUS_SUCCESS;
    Irp->IoStatus.Information = 0;
    IoCompleteRequest(Irp, IO_NO_INCREMENT);
    return STATUS_SUCCESS;
}

NTSTATUS FooDispatchRead(PDEVICE_OBJECT DeviceObject, PIRP Irp)
{
    UNREFERENCED_PARAMETER(DeviceObject);
    Irp->IoStatus.Status = STATUS_SUCCESS;
    Irp->IoStatus.Information = 0;
    IoCompleteRequest(Irp, IO_NO_INCREMENT);
    return STATUS_SUCCESS;
}

NTSTATUS FooDispatchWrite(PDEVICE_OBJECT DeviceObject, PIRP Irp)
{
    UNREFERENCED_PARAMETER(DeviceObject);
    Irp->IoStatus.Status = STATUS_SUCCESS;
    Irp->IoStatus.Information = 0;
    IoCompleteRequest(Irp, IO_NO_INCREMENT);
    return STATUS_SUCCESS;
}

NTSTATUS FooDispatchIoctl(PDEVICE_OBJECT DeviceObject, PIRP Irp)
{
    PIO_STACK_LOCATION stack = IoGetCurrentIrpStackLocation(Irp);
    UNREFERENCED_PARAMETER(DeviceObject);
    UNREFERENCED_PARAMETER(stack);
    Irp->IoStatus.Status = STATUS_SUCCESS;
    Irp->IoStatus.Information = 0;
    IoCompleteRequest(Irp, IO_NO_INCREMENT);
    return STATUS_SUCCESS;
}

NTSTATUS FooIoCompletion(PDEVICE_OBJECT DeviceObject, PIRP Irp, PVOID Context)
{
    UNREFERENCED_PARAMETER(DeviceObject);
    UNREFERENCED_PARAMETER(Irp);
    UNREFERENCED_PARAMETER(Context);
    return STATUS_SUCCESS;
}
