"""Corporate package-feed host pattern shared by both scanners.

`test_no_corporate_feeds.py` rejects these hosts anywhere outside `ref/` and
`unfettered-skills/`; `check_unfettered.py` rejects them inside
`unfettered-skills/`. Stdlib only: a bytes regex, unchanged from its original
home in the repo-wide test.
"""

import re

FEED_HOST = re.compile(
    rb"""
    (?<![a-z0-9_.-])
    (?:[a-z0-9_-]+\.)*
    (?:
        pkgs\.(?:visualstudio|dev\.azure)\.com
        | [a-z0-9_-]*packagefeed[p]roxy[a-z0-9_-]*(?:\.[a-z0-9_-]+)*
        | (?:visualstudio\.com|dev\.azure\.com)
          (?=(?::[0-9]+)?/(?:[^\s"'<>?#]*/)?_packaging(?:[/\s"'<>?#]|$))
    )
    (?![a-z0-9_-]|\.[a-z0-9_-])
    """,
    re.IGNORECASE | re.VERBOSE,
)
