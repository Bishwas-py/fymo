"""EmailSender Protocol + the default logging implementation.

App authors swap the implementation via `fymo.yml`:

    auth:
      email_sender: my_app.email.SmtpEmailSender

The class is instantiated with a single positional argument: the project
root path — same convention as `auth.user_store` (see `fymo/auth/store.py`).
Fymo core ships NO SMTP dependency; the default just logs the verification
link so dev/test environments work without any mail configuration.
"""
from __future__ import annotations

import logging
from pathlib import Path
from typing import Protocol, runtime_checkable

logger = logging.getLogger("fymo.auth.email")


@runtime_checkable
class EmailSender(Protocol):
    """The interface every email-sending implementation must satisfy."""

    def send_verification(self, email: str, link: str) -> None: ...
    def send_password_reset(self, email: str, link: str) -> None: ...


class LoggingEmailSender:
    """Default sender: logs the verification/reset link instead of sending mail.

    Accepts (and ignores) `project_root` so it can be instantiated the same
    way a configured `auth.email_sender` class would be.
    """

    def __init__(self, project_root: Path | None = None):
        self.project_root = project_root

    def send_verification(self, email: str, link: str) -> None:
        logger.info("verification email for %s: %s", email, link)

    def send_password_reset(self, email: str, link: str) -> None:
        logger.info("password reset email for %s: %s", email, link)
