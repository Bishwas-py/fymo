# Journal Entry 041: The Version That Lied Politely

**Date**: July 18, 2026
**Focus**: fymo --version reports the installed version instead of a fossil
**Status**: Shipped

## Two Sources, One Truth, Zero Sync

`fymo --version` said 0.1.0. PyPI said 0.19.0. Both were telling the
truth about what they were looking at: the CLI read a hardcoded string in
`__init__.py` that nobody had touched since the first release, while the
package metadata tracked pyproject.toml the way build tools guarantee.
Two copies of a fact drift the moment nobody is forced to update both,
and nothing forced it, so they drifted for eighteen minor versions.

The sting was in how it surfaced: mid benchmark prep, checking whether a
venv upgrade had taken. The CLI said 0.1.0 and for a minute the upgrade
looked broken. It was not. The version reporter was the only broken
thing, which is a special kind of bug, the instrument lying about the
patient.

## Delete the Copy, Keep the Question

The fix deletes the second copy instead of remembering to sync it:
`__version__` now asks `importlib.metadata` at import time, which reads
what the installer actually wrote from pyproject.toml. One source, one
answer. A bare source checkout with no installed metadata gets an honest
`0.0.0.dev0` instead of a confident wrong number.

The tests are the part I care about: they never mention a version string.
One pins `fymo.__version__` against the installed metadata, one pins the
CLI's output against the same. Any future hardcoded value fails both on
the next release bump, automatically, which is the property a fix like
this has to have. A test asserting "0.19.0" would just be the third copy
of the fact, waiting its turn to lie.

---

*End of Journal Entry 041*
