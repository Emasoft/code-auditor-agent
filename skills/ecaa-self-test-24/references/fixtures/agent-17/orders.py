# ruff: noqa
# Intentionally contains the bugs each detector should catch.
# Convention used across this module: every public getter returns
# Result[Value, Error] — never raises.
def get_order(id: int):
    if not exists(id):
        return Err(OrderError.NOT_FOUND)
    return Ok(Order(id))
