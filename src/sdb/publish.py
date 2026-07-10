"""
SDBS publish — publishable artifact bundle generation.

Generates a reproducible, citable artifact bundle per target in ``_publish/{target}/``,
containing TeX sources, PDF, clean markdown, C2PA signatures, and Zenodo-compatible
metadata.

This module is called as a post-job from `sdb build --publish` after the full
post-render sequence completes.
"""

from __future__ import annotations

import logging
from pathlib import Path
from typing import Any, Dict, List, Optional

logger = logging.getLogger(__name__)


PUBLISH_DIR_NAME = "_publish"


def get_publish_dir(docs_root: Path) -> Path:
    """Return the publish output directory (``_publish`` sibling to docs root)."""
    return docs_root.parent / PUBLISH_DIR_NAME


def capture_tex_sources(
    docs_root: Path,
    targets: List[str],
    target_config: Dict[str, Dict[str, Any]],
    publish_dir: Path,
) -> None:
    """
    For each target, run ``quarto render --to tex`` and copy the generated
    TeX source tree into ``_publish/{target}/source/``.

    To be implemented in Phase 2.
    """
    logger.info(
        "TeX source capture not yet implemented. "
        "Would capture %d target(s) to %s",
        len(targets), publish_dir,
    )


def transform_llms_to_pub_md(
    docs_root: Path,
    targets: List[str],
    publish_dir: Path,
) -> None:
    """
    Transform ``_llms/*.llms.md`` into clean markdown files in the publish bundle,
    stripping LLM-specific metadata/prompts.

    To be implemented in Phase 2.
    """
    logger.info(
        "LLMS-to-pub.md transformation not yet implemented. "
        "Would process %d target(s).",
        len(targets),
    )


def sign_publish_artifacts(
    docs_root: Path,
    targets: List[str],
    target_config: Dict[str, Dict[str, Any]],
    publish_dir: Path,
) -> None:
    """
    C2PA-sign the PDF and markdown files in each publish bundle.

    To be implemented in Phase 2 (requires C2PA refactor in Phase 3 first).
    """
    logger.info(
        "C2PA signing for publish artifacts not yet implemented. "
        "Would sign %d target(s).",
        len(targets),
    )


def assemble_publish_bundles(
    docs_root: Path,
    targets: List[str],
    target_config: Dict[str, Dict[str, Any]],
    publish_dir: Path,
) -> None:
    """
    Assemble all artifacts into ``_publish/{target}/`` directory structure.

    To be implemented in Phase 2.
    """
    logger.info(
        "Bundle assembly not yet implemented. "
        "Would assemble %d target(s) into %s",
        len(targets), publish_dir,
    )


def generate_metadata_yaml(
    docs_root: Path,
    target: str,
    target_config: Dict[str, Any],
    bundle_dir: Path,
) -> None:
    """
    Extract metadata from Quarto config and generate ``metadata.yaml`` for Zenodo.

    To be implemented in Phase 2.
    """
    logger.info(
        "Metadata generation for '%s' not yet implemented.",
        target,
    )


def upload_to_zenodo(
    publish_dir: Path,
    targets: List[str],
    sandbox: bool = False,
) -> None:
    """
    Upload publish bundles to Zenodo and request DOI.

    To be implemented in Phase 4 (requires Zenodo client first).
    """
    logger.info(
        "Zenodo upload not yet implemented (sandbox=%s). "
        "Would upload %d target(s) from %s",
        sandbox, len(targets), publish_dir,
    )
