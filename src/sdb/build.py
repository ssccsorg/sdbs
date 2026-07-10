"""
SDBS build -- Quarto build orchestration.

This is the main orchestration module. It builds on top of the extracted
sub-modules (config, hash, quarto, render, artifact, merge) to implement
the full build pipeline: discovery, caching, rendering, artifact generation,
merge, and cleanup.
"""

from __future__ import annotations

import logging
import os
import shutil
import subprocess
import sys
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path
from typing import Any, Callable, Dict, List, Optional, Tuple

from .artifact import (
    get_cached_artifact_path as _get_cached_artifact_path,
    get_enabled_handlers,
    get_linked_artifact_extensions,
    find_cached_artifact as _find_cached_artifact,
)
from .config import (
    BUILD_TEMP_DIR,
    JUPYTER_CACHE_DIR,
    ConfigManager,
    CleanupManager,
)
from .hash import HashManager
from .merge import merge_dirs
from .quarto import QuartoInspector
from .render import (
    NON_DETERMINISTIC_FORMATS,
    CommandRunner,
    _render_formats,
)
from sdb.resolve import resolve_all
from sdb.utils.latest import generate_latest_docs
from sdb.utils.llms import generate_llms_txt

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Module-level global mutable state
# ---------------------------------------------------------------------------

EXTERNAL_CONFIG: Dict[str, Any] = {}
TARGET_CONFIG: Dict[str, Dict[str, Any]] = {}
BUILD_FUNCTIONS: Dict[str, Callable[..., bool]] = {}
OUTPUT_DIR_TARGETS: set = set()
_INITIAL_CACHED_TARGETS: Optional[set] = None
PROJECT_ROOT: Optional[Path] = None  # Set by initialize_config


# ---------------------------------------------------------------------------
# Standalone function aliases that delegate to extracted module classes
# ---------------------------------------------------------------------------


def ignore_quarto_artifacts() -> Callable[[str, list[str]], set[str]]:
    return CleanupManager().ignore_quarto_artifacts()


def compute_file_hash(path: Path) -> str:
    return HashManager.compute_file_hash(path)


def compute_quarto_file_hash_with_deps(file_path: Path, docs_root: Path) -> str:
    return HashManager.compute_quarto_file_hash_with_deps(file_path, docs_root)


def target_produces_pdf(config: Dict[str, Any]) -> bool:
    return QuartoInspector.target_produces_pdf(config)


def inspect_quarto_file(file_path: Path) -> Optional[Dict[str, Any]]:
    return QuartoInspector.inspect(file_path)


def get_formats_from_quarto_file(file_path: Path) -> List[str]:
    return QuartoInspector.get_formats(file_path)


def get_format_output_path(file_path: Path, fmt: str) -> Optional[Path]:
    return QuartoInspector.get_output_path(file_path, fmt)


def get_moved_path_for_format(
    qmd_path: Path,
    fmt: str,
    config: Optional[Dict[str, Any]],
    output_dir: Optional[Path],
    docs_root: Path,
    source_path: Path,
) -> Optional[Path]:
    return QuartoInspector.get_moved_path(
        qmd_path, fmt, config, output_dir, docs_root, source_path
    )


def find_existing_output(
    qmd_path: Path,
    fmt: str,
    config: Optional[Dict[str, Any]],
    output_dir: Optional[Path],
    docs_root: Path,
) -> Optional[Path]:
    return QuartoInspector.find_existing_output(
        qmd_path, fmt, config, output_dir, docs_root
    )


def get_cache_dir(qmd_path: Path) -> Path:
    return QuartoInspector.get_cache_dir(qmd_path)


def get_cache_dir_for_target(qmd_path: Path, target_name: str) -> Path:
    return QuartoInspector.get_cache_dir_for_target(qmd_path, target_name)


def get_cache_base(docs_root: Optional[Path] = None) -> Path:
    """Return the system-wide cache base directory.

    Uses the module-level ``PROJECT_ROOT`` (set by ``initialize_config``)
    when available, falling back to ``docs_root.parent``.
    """
    if PROJECT_ROOT is not None:
        return PROJECT_ROOT / "_cached"
    if docs_root is not None:
        return docs_root.parent / "_cached"
    return Path.cwd().parent / "_cached"


def format_to_extension(fmt: str) -> str:
    return QuartoInspector.format_to_extension(fmt)


def clean_quarto_artifacts(docs_root: Path) -> bool:
    return CleanupManager().clean(docs_root)


def load_external_config(config_path: Optional[Path]) -> Dict[str, Any]:
    return ConfigManager.load_external_config(config_path)


def get_exclude_patterns(external_config: Dict[str, Any]) -> List[str]:
    return ConfigManager.get_exclude_patterns(external_config)


def get_target_config_from_external(
    external_config: Dict[str, Any],
) -> Dict[str, Dict[str, Any]]:
    return ConfigManager.get_target_config_from_external(external_config)


def matches_gitignore_pattern(rel_path: Path, patterns: List[str]) -> bool:
    return ConfigManager.matches_gitignore_pattern(rel_path, patterns)


def discover_quarto_targets(
    docs_root: Path, exclude_patterns: Optional[List[str]] = None
) -> Dict[str, Dict[str, Any]]:
    return ConfigManager.discover_quarto_targets(docs_root, exclude_patterns)


def get_target_config(
    docs_root: Path, external_config: Optional[Dict[str, Any]] = None
) -> Dict[str, Dict[str, Any]]:
    return ConfigManager.get_target_config(docs_root, external_config)


def run_command(cmd: List[str], cwd: Optional[Path] = None) -> bool:
    return CommandRunner.run(cmd, cwd)


def get_cached_artifact_path(
    target_name: str,
    hash_str: str,
    fmt: str,
    docs_root: Path,
    linked_ext: Optional[str] = None,
) -> Path:
    # Use PROJECT_ROOT for cache paths (consistent across website mode)
    project_root = PROJECT_ROOT if PROJECT_ROOT else docs_root.parent
    return _get_cached_artifact_path(
        target_name, hash_str, fmt, project_root, linked_ext=linked_ext
    )


def find_cached_artifact(
    target_name: str,
    hash_str: str,
    fmt: str,
    docs_root: Path,
    linked_ext: Optional[str] = None,
) -> Optional[Path]:
    project_root = PROJECT_ROOT if PROJECT_ROOT else docs_root.parent
    return _find_cached_artifact(
        target_name, hash_str, fmt, project_root, linked_ext=linked_ext
    )


# ---------------------------------------------------------------------------
# Caching helpers
# ---------------------------------------------------------------------------


def capture_initial_cached_targets(docs_root: Path) -> None:
    """
    Capture the set of cached target names before build starts.
    This is used to detect if the document set has changed during the build.
    """
    global _INITIAL_CACHED_TARGETS
    cache_base = get_cache_base(docs_root)
    if not cache_base.exists():
        _INITIAL_CACHED_TARGETS = set()
    else:
        _INITIAL_CACHED_TARGETS = {d.name for d in cache_base.iterdir() if d.is_dir()}


def get_initial_cached_targets() -> set:
    """Return the snapshot of cached target names captured before build starts."""
    if _INITIAL_CACHED_TARGETS is None:
        return set()
    return _INITIAL_CACHED_TARGETS


def should_rerender_for_sidebar(build_targets: set, docs_root: Path) -> bool:
    """
    Check if HTML must be re-rendered to update sidebar.
    Returns True if:
      - Any target in the build set is not yet cached (new files added), OR
      - Any cached target is not in the build set (files deleted/changed)

    This ensures the sidebar is updated whenever the document set changes,
    whether by addition, deletion, or modification of source files.
    """
    cached_targets = get_initial_cached_targets()
    has_new_files = not build_targets.issubset(cached_targets)
    has_deleted_files = not cached_targets.issubset(build_targets)
    return has_new_files or has_deleted_files


def cache_site_directory(target_name: str, hash_str: str, site_dir: Path, docs_root: Path) -> bool:
    """
    Cache the entire _site directory for a target (including site_libs).
    The directory is copied to _cached/{target}/{hash}/site/.
    Returns True on success, False on error.
    """
    if not site_dir.exists():
        logger.warning(f"Site directory {site_dir} does not exist, nothing to cache.")
        return False
    cache_base = get_cache_base(docs_root) / target_name / hash_str / "site"
    if cache_base.exists():
        shutil.rmtree(cache_base, ignore_errors=True)
    try:
        shutil.copytree(site_dir, cache_base)
        logger.info(f"Cached site directory for {target_name} at {cache_base}")
        return True
    except Exception as e:
        logger.error(f"Failed to cache site directory for {target_name}: {e}")
        return False


def restore_site_directory(target_name: str, hash_str: str, dest_dir: Path, docs_root: Path) -> bool:
    """
    Restore a cached site directory to dest_dir (should be the _site directory).
    Returns True on success, False if cache missing or error.
    """
    cache_dir = get_cache_base(docs_root) / target_name / hash_str / "site"
    if not cache_dir.exists():
        logger.debug(f"No cached site directory for {target_name} ({hash_str})")
        return False
    dest_dir.parent.mkdir(parents=True, exist_ok=True)
    if dest_dir.exists():
        shutil.rmtree(dest_dir, ignore_errors=True)
    try:
        shutil.copytree(cache_dir, dest_dir)
        logger.info(f"Restored cached site directory for {target_name} to {dest_dir}")
        return True
    except Exception as e:
        logger.error(f"Failed to restore cached site directory for {target_name}: {e}")
        return False


def get_cache_file(qmd_path: Path, fmt: str) -> Path:
    """
    Return the cache file path for a given format.
    For index.qmd files, uses the parent folder name for cache directory.
    """
    if qmd_path.stem.lower() == "index":
        parent_name = qmd_path.parent.name
        if parent_name and parent_name != ".":
            return qmd_path.parent / f"{parent_name}_cached" / f"rendered_{fmt}.txt"
    return get_cache_dir(qmd_path) / f"rendered_{fmt}.txt"


def read_hash_pair(cache_file: Path) -> Optional[Tuple[str, str]]:
    """
    Read hash pair from cache file.
    Returns (qmd_hash, output_hash) or None if missing/malformed.
    """
    if not cache_file.exists():
        return None
    try:
        with open(cache_file, "r") as f:
            line = f.read().strip()
        if "_" in line:
            a, b = line.split("_", 1)
            if len(a) == 64 and len(b) == 64:
                return (a, b)
    except Exception:
        pass
    return None


def write_hash_pair(cache_file: Path, qmd_hash: str, output_hash: str) -> None:
    """Write hash pair to cache file."""
    cache_file.parent.mkdir(parents=True, exist_ok=True)
    with open(cache_file, "w") as f:
        f.write(f"{qmd_hash}_{output_hash}")


# ---------------------------------------------------------------------------
# Render decision helpers
# ---------------------------------------------------------------------------


def should_render_format(
    file_path: Path,
    fmt: str,
    target_name: str,
    docs_root: Path,
    config: Optional[Dict[str, Any]] = None,
    output_dir: Optional[Path] = None,
) -> bool:
    """
    Determine whether a given format needs to be rendered based on cached QMD hash.
    For non-deterministic formats, we only compare the QMD hash; the output hash
    is ignored to avoid unnecessary re-renders when the generated file would be
    slightly different (e.g. due to timestamps). Deterministic formats are always
    rendered.
    Returns True if render is needed, False if up-to-date.
    """
    if fmt not in NON_DETERMINISTIC_FORMATS:
        logger.info(f"{fmt} is considered deterministic, always render.")
        return True

    qmd_hash = compute_quarto_file_hash_with_deps(file_path, docs_root)
    logger.info(
        f"Checking cache for {target_name} ({fmt}): QMD hash {qmd_hash[:16]}..."
    )

    cached = find_cached_artifact(target_name, qmd_hash, fmt, docs_root)
    if cached is not None:
        output_path = get_format_output_path(file_path, fmt)
        if output_path is None:
            logger.warning(
                f"Cannot determine output path for {target_name} ({fmt}), proceeding with render."
            )
            return True
        output_path.parent.mkdir(parents=True, exist_ok=True)
        try:
            shutil.copy2(cached, output_path)
            logger.info(
                f"Cache hit for {target_name} ({fmt}), copied cached artifact to {output_path}"
            )
        except Exception as e:
            logger.warning(
                f"Failed to copy cached artifact for {target_name} ({fmt}): {e}, proceeding with render."
            )
            return True
        cfg = config or {}
        for linked_ext in get_linked_artifact_extensions(fmt, cfg):
            cached_linked = find_cached_artifact(
                target_name, qmd_hash, fmt, docs_root, linked_ext=linked_ext
            )
            if cached_linked is not None:
                linked_stem = file_path.stem
                linked_output_path = output_path.parent / f"{linked_stem}.{linked_ext}"
                try:
                    shutil.copy2(cached_linked, linked_output_path)
                    logger.info(
                        f"Restored cached linked artifact ({linked_ext}) to {linked_output_path}"
                    )
                except Exception as e:
                    logger.warning(
                        f"Failed to copy cached linked artifact for {target_name} ({fmt}): {e}"
                    )
        return False

    logger.info(f"Cache miss for {target_name} ({fmt}) - QMD hash {qmd_hash[:16]}...")
    return True


def update_format_cache(
    file_path: Path,
    fmt: str,
    output_path: Path,
    docs_root: Path,
    target_name: Optional[str] = None,
    linked_artifacts: Optional[Dict[str, Path]] = None,
) -> None:
    """Update cache after successful render of a specific format.

    Args:
        file_path: Path to the source QMD file
        fmt: Output format (pdf, html, etc.)
        output_path: Path to the rendered output file
        docs_root: Root directory of documentation
        target_name: Name of the build target
        linked_artifacts: Dict mapping linked file extension -> path to the linked artifact file
    """
    qmd_hash = compute_quarto_file_hash_with_deps(file_path, docs_root)
    output_hash = compute_file_hash(output_path)
    logger.info(
        f"Updating {fmt} cache for {file_path.name}: output hash {output_hash[:16]}..."
    )

    if target_name is not None:
        target_cache_dir = get_cache_base(docs_root) / target_name
        if target_cache_dir.exists():
            try:
                for existing_hash_dir in target_cache_dir.iterdir():
                    if (
                        existing_hash_dir.is_dir()
                        and existing_hash_dir.name != qmd_hash
                    ):
                        shutil.rmtree(existing_hash_dir)
                        logger.info(
                            f"Deleted old cache directory for target '{target_name}' "
                            f"(hash: {existing_hash_dir.name[:16]}...) to prevent accumulation"
                        )
            except Exception as e:
                logger.warning(
                    f"Failed to delete old cache for target '{target_name}': {e}"
                )

        cache_dir = get_cache_base(docs_root) / target_name / qmd_hash
        cache_dir.mkdir(parents=True, exist_ok=True)
        ext = format_to_extension(fmt)
        artifact_name = f"{target_name}.{ext}"
        artifact_path = cache_dir / artifact_name
        try:
            shutil.copy2(output_path, artifact_path)
            logger.info(f"Cached artifact for {target_name} ({fmt}) at {artifact_path}")
        except Exception as e:
            logger.warning(f"Failed to cache artifact for {target_name} ({fmt}): {e}")

        if linked_artifacts:
            for linked_ext, linked_path in linked_artifacts.items():
                if linked_path is not None and linked_path.exists():
                    linked_cache_name = f"{target_name}.{linked_ext}"
                    linked_cache_path = cache_dir / linked_cache_name
                    try:
                        shutil.copy2(linked_path, linked_cache_path)
                        logger.info(
                            f"Cached linked artifact ({linked_ext}) for {target_name} ({fmt}) at {linked_cache_path}"
                        )
                    except Exception as e:
                        logger.warning(
                            f"Failed to cache linked artifact ({linked_ext}) for {target_name} ({fmt}): {e}"
                        )

    cache_file = get_cache_file(file_path, fmt)
    write_hash_pair(cache_file, qmd_hash, output_hash)


def refresh_cache_for_target(
    target: str,
    output_dir: Optional[Path] = None,
    docs_root: Optional[Path] = None,
    target_config: Optional[Dict] = None,
) -> bool:
    """
    Refresh the cache entries for a given target.
    Updates the cache only when the QMD hash has not changed (i.e., the source is
    identical to when the cache was created). If the QMD hash changed, the cache
    is removed to force a rebuild on the next build. This avoids recording stale
    outputs and eliminates reliance on file timestamps.
    Returns True on success, False on failure.
    """
    if docs_root is None:
        docs_root = Path.cwd()
    if target_config is None:
        target_config = TARGET_CONFIG

    if target not in target_config:
        logger.error(f"Unknown target '{target}'")
        return False
    config = target_config[target]
    qmd_path = docs_root / config["qmd"]
    if not qmd_path.exists():
        logger.error(f"Qmd file not found: {qmd_path}")
        return False

    formats = get_formats_from_quarto_file(qmd_path)
    if not formats:
        logger.info(
            f"Target {target} has no defined output formats, skipping cache refresh."
        )
        return True

    current_qmd_hash = compute_quarto_file_hash_with_deps(qmd_path, docs_root)

    for fmt in formats:
        cache_file = get_cache_file(qmd_path, fmt)
        existing_cache = read_hash_pair(cache_file)

        output_path = find_existing_output(qmd_path, fmt, config, output_dir, docs_root)

        if output_path and output_path.exists():
            if existing_cache is not None and existing_cache[0] == current_qmd_hash:
                update_format_cache(qmd_path, fmt, output_path, docs_root, target_name=target)
                logger.info(f"Updated {fmt} cache for {target}")
            else:
                if cache_file.exists():
                    cache_file.unlink()
                    logger.info(
                        f"Removed cache file for {target} ({fmt}) - QMD changed or cache missing"
                    )
                else:
                    logger.info(
                        f"No cache file for {target} ({fmt}) - will rebuild on next run"
                    )
                if existing_cache is not None:
                    old_hash = existing_cache[0]
                    old_cache_dir = get_cache_base(docs_root) / target / old_hash
                    if old_cache_dir.exists():
                        shutil.rmtree(old_cache_dir)
                        logger.info(
                            f"Removed new cache directory for {target} ({fmt}) - QMD changed"
                        )
        else:
            if cache_file.exists():
                cache_file.unlink()
                logger.info(f"Removed cache file for {target} ({fmt} output missing)")
            else:
                logger.info(f"No cache file for {target} ({fmt} output missing)")
    return True


# ---------------------------------------------------------------------------
# Pre-build / post-render command runners
# ---------------------------------------------------------------------------


# Default pre-build sequence (always runs first, before user config)
_DEFAULT_PRE_BUILD: List[Callable[[Path], Any] | List[str]] = [
    generate_latest_docs,
    resolve_all,
    ["rumdl", "fmt", ".", "--silent", "--disable", "MD036"],
]

# Default post-render sequence (always runs after build)
_DEFAULT_POST_RENDER: List[Callable[[Path], Any] | List[str]] = [
    generate_llms_txt,
]


def _run_default_sequence(
    steps: List[Callable[[Path], Any] | List[str]],
    docs_root: Path,
    phase: str,
) -> None:
    """Run a sequence of default steps, each either a callable or a
    subprocess command list."""
    logger.info(
        "Running %d default %s step(s)...", len(steps), phase.lower()
    )
    for step in steps:
        if callable(step):
            logger.info(
                "%s: calling %s(docs_root=%s)", phase, step.__name__, docs_root
            )
            try:
                step(docs_root)
            except Exception as e:
                logger.warning(
                    "%s: %s raised: %s, continuing...",
                    phase, step.__name__, e,
                )
        else:
            executable = step[0]
            if not shutil.which(executable):
                logger.info(
                    "%s: '%s' not found in PATH, skipping.", phase, executable
                )
                continue
            logger.info("%s: running %s", phase, " ".join(step))
            try:
                result = subprocess.run(
                    step, cwd=docs_root, capture_output=True, text=True
                )
                if result.stdout:
                    logger.debug(result.stdout.strip())
                if result.stderr:
                    logger.warning(result.stderr.strip())
                if result.returncode != 0:
                    logger.warning(
                        "%s command '%s' failed with exit code "
                        "%d, continuing...",
                        phase, executable, result.returncode,
                    )
                else:
                    logger.info(
                        "%s command '%s' succeeded.", phase, " ".join(step)
                    )
            except Exception as e:
                logger.warning(
                    "%s command '%s' raised: %s, continuing...",
                    phase, executable, e,
                )