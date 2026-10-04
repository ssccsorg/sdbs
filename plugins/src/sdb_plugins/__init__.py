"""
Reference deploy channels shipped with sdbs.

The deploy engine is provider-neutral and lives in :mod:`sdb.deploy`, inside the
``sdb`` package. A channel is a plugin, and this package, at the repository root
rather than inside ``sdb``, holds the channels sdbs ships. An external package
adds one through the ``sdb.deploy`` entry point group without touching the
engine. The command line is the composition root: it asks for these shipped
channels and passes them to the engine's registry, so the ``sdb`` package never
imports a channel and contains no channel code.
"""

from __future__ import annotations

from typing import List

from sdb.deploy import DeployPlugin
from .s3 import S3DeployPlugin


def builtin_plugins() -> List[DeployPlugin]:
    return [S3DeployPlugin()]


__all__ = ["builtin_plugins", "S3DeployPlugin"]
