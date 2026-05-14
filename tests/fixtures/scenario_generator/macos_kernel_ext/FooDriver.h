// fixture for macos_kernel_ext
// Header for the FooDriver IOKit class — the discoverer picks up the
// OSDeclareDefaultStructors invocation as a MODULE_INIT marker.

#ifndef FOO_DRIVER_H
#define FOO_DRIVER_H

#include <IOKit/IOService.h>

class FooDriver : public IOService
{
    OSDeclareDefaultStructors(FooDriver)

public:
    virtual bool init(OSDictionary *dict) override;
    virtual void free(void) override;
    virtual bool start(IOService *provider) override;
    virtual void stop(IOService *provider) override;
    virtual IOReturn message(UInt32 type, IOService *provider, void *arg) override;
};

#endif // FOO_DRIVER_H
