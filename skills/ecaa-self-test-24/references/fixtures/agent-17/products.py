# ruff: noqa
# Intentionally contains the bugs each detector should catch.
def get_product(id: int):
    if not exists(id):
        return Err(ProductError.NOT_FOUND)
    return Ok(Product(id))
