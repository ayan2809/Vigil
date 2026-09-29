"""Root pytest config.

`test_smtp.py` and `test_smtp_noauth.py` at the repo root are manual SMTP scratch scripts that
connect to the mail server at import time. Never collect them, even for `pytest .`.
"""

collect_ignore = ["test_smtp.py", "test_smtp_noauth.py"]
