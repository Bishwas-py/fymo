"""Build a single JobProvider from fymo.yml's `jobs:` config.

Mirrors fymo.auth.providers.registry's escape hatch exactly: a bare string
for a built-in, or an object with a `type` (built-in) or `class` (dotted
path to a custom provider) key plus any extra kwargs.
"""
from __future__ import annotations

from typing import Any

from fymo.core.providers import ProviderConfigError, instantiate_provider
from fymo.jobs.providers.base import JobProvider
from fymo.jobs.providers.procrastinate import ProcrastinateJobProvider
from fymo.jobs.providers.threaded import ThreadedJobProvider

_BUILTINS = {
    "threaded": ThreadedJobProvider,
    "procrastinate": ProcrastinateJobProvider,
}


class JobProviderConfigError(ProviderConfigError):
    """Raised when `jobs.provider` can't be turned into a provider instance."""


def build_job_provider(config: Any) -> JobProvider:
    """Instantiate the configured job provider. Defaults to `threaded` when
    `jobs.provider` is unset (mirrors auth's default-to-`password`)."""
    return instantiate_provider(
        config,
        _BUILTINS,
        ThreadedJobProvider,
        JobProviderConfigError,
        what="job provider",
        config_key="jobs.provider",
    )
