# ruff: noqa
# Intentionally contains the bugs each detector should catch.
def get_user(id: int):
    if not exists(id):
        return Err(UserError.NOT_FOUND)
    return Ok(User(id))
