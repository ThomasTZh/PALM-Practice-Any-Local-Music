#!/usr/bin/env python3
"""External uninstall helper.

The control window writes uninstall.json and launches this helper before
quitting. It waits for the app process, removes the app folder and shortcuts,
and deletes the data root only when the user explicitly chose delete-data.
"""

from __future__ import annotations

# The implementation is shared with update_helper.py so both helpers have the
# same wait/rollback semantics and can be distributed as one small directory.
from update_helper import main

if __name__ == "__main__":
    raise SystemExit(main())
