"""Precision fixture (clean-but-suspicious): naming that INVITES a
docstring-vs-code contradiction claim, while the code is actually correct.

`batch_line_index` sounds batch-relative, and a careless reading of
`find_in_batch` makes `idx` look like an absolute offset. In fact the contract
is consistent: `find_in_batch` returns a 0-based index WITHIN the batch, and
`to_absolute` converts it by adding `batch_start`. The efficacy gate asserts
this file gets ZERO confirmed CRITICAL/MAJOR findings (an initial flag that the
verifier refutes after a forced re-read counts as a pass — that is the
contradiction-resolution mechanism working as designed).
"""


def find_in_batch(batch_lines: list[str], needle: str) -> int:
    """Return the 0-based index of `needle` WITHIN this batch, or -1."""
    for batch_line_index, line in enumerate(batch_lines):
        if needle in line:
            return batch_line_index
    return -1


def to_absolute(batch_start: int, batch_line_index: int) -> int:
    """Convert a batch-relative index to the absolute file line index."""
    if batch_line_index < 0:
        raise ValueError("needle not found in batch")
    return batch_start + batch_line_index
