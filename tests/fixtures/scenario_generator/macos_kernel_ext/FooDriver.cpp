// fixture for macos_kernel_ext
// Implementation of the FooDriver IOKit class — the discoverer picks
// up OSDefineMetaClassAndStructors + each lifecycle method.

#include "FooDriver.h"

OSDefineMetaClassAndStructors(FooDriver, IOService)

bool FooDriver::init(OSDictionary *dict)
{
    if (!super::init(dict)) {
        return false;
    }
    return true;
}

void FooDriver::free(void)
{
    super::free();
}

bool FooDriver::start(IOService *provider)
{
    if (!super::start(provider)) {
        return false;
    }
    registerService();
    return true;
}

void FooDriver::stop(IOService *provider)
{
    super::stop(provider);
}

IOReturn FooDriver::message(UInt32 type, IOService *provider, void *arg)
{
    (void)type;
    (void)provider;
    (void)arg;
    return kIOReturnSuccess;
}
