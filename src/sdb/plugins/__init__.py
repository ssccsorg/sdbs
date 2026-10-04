"""
Reference deploy channels shipped with sdbs.

The deploy engine is provider-neutral and lives in :mod:`sdb.deploy`. A channel
is a plugin; this package holds the channels sdbs ships, and an external
package adds one through the ``sdb.deploy`` entry point group without touching
the engine. The command line is the composition root: it asks for these
built-ins and passes them to the engine's registry, so the engine itself never
imports a channel.
"""

from __future__ import annotations

from typing import List

from ..deploy import DeployPlugin
from .s3 import S3DeployPlugin


def builtin_plugins() -> List[DeployPlugin]:
    return [S3DeployPlugin()]


__all__ = ["builtin_plugins", "S3DeployPlugin"]
