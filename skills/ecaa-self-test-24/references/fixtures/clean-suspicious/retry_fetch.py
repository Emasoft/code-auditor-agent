"""Precision fixture (clean-but-suspicious): bounded retry that LOOKS like it
swallows errors but is actually correct fail-fast.

An eager auditor flags "retry loop hides the exception" or "unreachable code
after the loop". Both are FALSE: the final attempt re-raises (`i == attempts-1`
branch), so no error is ever swallowed, and the trailing AssertionError is a
deliberate can't-happen guard. The efficacy gate asserts this file gets ZERO
confirmed CRITICAL/MAJOR findings (flag-then-refuted counts as a pass).
"""

import urllib.request


def _fetch(url: str) -> bytes:
    with urllib.request.urlopen(url, timeout=10) as resp:
        return resp.read()


def retry_fetch(url: str, attempts: int = 3) -> bytes:
    """Fetch with bounded retries; raises on the final failure (fail-fast)."""
    for i in range(attempts):
        try:
            return _fetch(url)
        except TimeoutError:
            if i == attempts - 1:
                raise  # final attempt: propagate — nothing is swallowed
    raise AssertionError("unreachable: loop always returns or raises")
