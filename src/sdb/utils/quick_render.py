"""
Quick render: locate one or more .qmd files by short name and render them.

Provides a convenience subcommand ``sdb render <name>`` so that, for example,
``sdb render kv`` finds ``docs/projects/syntagma/tagma/kv.qmd`` and runs
``quarto render`` on it automatically.
"""

from __future__ import annotations

import logging
import subprocess
from pathlib import Path
from typing import Any, Dict, List, Optional

logger = logging.getLogger(__name__)



def _stem(file_path: Path) -> str:
    """Return the file stem (filename without suffix)."""
    return file_path.stem


def find_build_yml(start: Optional[Path] = None) -> Optional[Path]:
    """Locate a ``build.yml`` starting from *start*.

    Search order:
      1. *start* itself.
      2. Immediate subdirectories of *start* (common layout where config
         lives in a ``docs/`` subdirectory).
      3. Ancestors of *start* (walk up).

    Returns the path to the first ``build.yml`` found, or ``None``.
    """
    if start is None:
        start = Path.cwd()
    start = start.resolve()

    # 1. Check *start* itself
    candidate = start / "build.yml"
    if candidate.exists():
        return candidate

    # 2. Check immediate subdirectories
    try:
        for child in start.iterdir():
            if child.is_dir():
                candidate = child / "build.yml"
                if candidate.exists():
                    return candidate
    except PermissionError:
        pass

    # 3. Walk up
    current = start
    while True:
        parent = current.parent
        if parent == current:
            break
        candidate = parent / "build.yml"
        if candidate.exists():
            return candidate
        current = parent

    return None


def load_exclude_patterns(build_yml: Path) -> List[str]:
    """Load exclude patterns from the given ``build.yml`` path.

    Uses the same config loading and pattern resolution that ``sdb build``
    uses, so that ``sdb render`` respects the same exclusions.
    """
    try:
        from sdb.config import ConfigManager
        cfg: Dict[str, Any] = ConfigManager.load_yaml_file(build_yml)
        return ConfigManager.get_exclude_patterns(cfg)
    except Exception as exc:
        logger.warning(
            "Failed to load exclusions from %s: %s", build_yml, exc
        )
        return []


def find_qmd_files(
    pattern: str,
    root: Optional[Path] = None,
    exclude_patterns: Optional[List[str]] = None,
) -> List[Path]:
    """Recursively search for .qmd files whose stem matches *pattern*.

    Matching strategy (in order of priority):
      1. Exact match (stem equals *pattern*).
      2. Suffix match (stem ends with *pattern*).
      3. Substring match (*pattern* appears anywhere in stem).

    If *pattern* contains a slash it is treated as a relative path fragment:
    only files whose relative path contains that fragment are returned.

    When *exclude_patterns* are provided (gitignore-style globs), files
    matching any of them are omitted.  This is consistent with how
    ``sdb build`` excludes files via ``build.yml``.

    Args:
        pattern:          Short name or path fragment to search for
                          (e.g. ``"kv"``, or ``"tagma/kv"``).
        root:             Directory to search under.  Defaults to the current
                          working directory.
        exclude_patterns: Optional list of gitignore-style glob patterns to
                          exclude.  Typically loaded from ``build.yml``.

    Returns:
        A list of matching ``Path`` objects, sorted by match quality (exact
        first, then suffix, then substring) and finally alphabetically.
    """
    if root is None:
        root = Path.cwd()

    candidates: List[Path] = list(root.rglob("*.qmd"))

    # Apply exclude patterns (same mechanism as sdb build)
    if exclude_patterns:
        from sdb.config import ConfigManager
        filtered: List[Path] = []
        for p in candidates:
            rel = p.relative_to(root)
            if ConfigManager.matches_gitignore_pattern(rel, exclude_patterns):
                logger.debug("Excluded %s (matches exclude pattern)", rel)
                continue
            filtered.append(p)
        candidates = filtered

    if not candidates:
        logger.warning("No .qmd files found under %s", root)
        return []

    # --- filtering -----------------------------------------------------------
    exact: List[Path] = []
    suffix: List[Path] = []
    substring: List[Path] = []

    for p in candidates:
        stem = _stem(p)

        if "/" in pattern:
            # Relative path fragment mode
            rel = p.relative_to(root)
            rel_str = str(rel.as_posix())
            if pattern in rel_str:
                exact.append(p)
            continue

        if stem == pattern:
            exact.append(p)
        elif stem.endswith(pattern) and stem != pattern:
            suffix.append(p)
        elif pattern in stem:
            substring.append(p)

    # --- ordering ------------------------------------------------------------
    def _sort_key(p: Path) -> tuple:
        rel = p.relative_to(root)
        return (len(rel.parts), str(rel))

    exact.sort(key=_sort_key)
    suffix.sort(key=_sort_key)
    substring.sort(key=_sort_key)

    return exact + suffix + substring


def render_qmd(
    qmd_path: Path,
    cwd: Optional[Path] = None,
    format: Optional[str] = None,
) -> bool:
    """Render a single .qmd file with ``quarto render``.

    Args:
        qmd_path: Path to the .qmd file.
        cwd:      Working directory for the Quarto process.  Defaults to the
                  parent of *qmd_path*.
        format:   Optional output format (e.g. ``"html"``, ``"pdf"``).
                  When omitted, Quarto uses the file's default format(s).

    Returns:
        ``True`` if rendering succeeded.
    """
    if cwd is None:
        cwd = qmd_path.parent

    if not qmd_path.exists():
        logger.error("File not found: %s", qmd_path)
        return False

    cmd = ["quarto", "render", str(qmd_path)]
    if format:
        cmd.extend(["--to", format])

    logger.info("Rendering %s …", qmd_path)
    try:
        result = subprocess.run(
            cmd,
            cwd=cwd,
            capture_output=True,
            text=True,
            check=False,
        )
        if result.stdout:
            for line in result.stdout.strip().splitlines():
                logger.info("  %s", line)
        if result.stderr:
            for line in result.stderr.strip().splitlines():
                logger.warning("  %s", line)
        if result.returncode != 0:
            logger.error(
                "quarto render failed for %s (exit code %d)",
                qmd_path, result.returncode,
            )
            return False
        logger.info("Rendered: %s", qmd_path)
        return True
    except FileNotFoundError:
        logger.error("quarto not found. Is Quarto CLI installed?")
        return False
    except Exception as e:
        logger.error("Unexpected error rendering %s: %s", qmd_path, e)
        return False


def select_qmd_files(
    pattern: str,
    root: Optional[Path] = None,
    prompt: bool = True,
    label: Optional[str] = None,
    exclude_patterns: Optional[List[str]] = None,
) -> Optional[List[Path]]:
    """Locate .qmd files matching *pattern* and let the user select which to render.

    This is the selection-only front-end used by the CLI handler to collect
    files across multiple patterns before rendering.  ``quick_render`` calls
    this internally.

    Behaviour when multiple files match:

    * If ``prompt=True`` (default) and more than one match is found, the
      user is prompted to select which ones to render.
    * If ``prompt=False``, all matches are returned without asking.

    Args:
        pattern:          Short name or path fragment.
        root:             Directory to search under.  Defaults to current
                          directory.
        prompt:           Whether to prompt on multiple matches.
        label:            Optional progress label prepended to the prompt
                          header (e.g. ``"1/3"``).  Ignored when *prompt*
                          is ``False``.
        exclude_patterns: Optional list of gitignore-style glob patterns
                          to exclude (loaded from ``build.yml``).

    Returns:
        A list of selected ``Path`` objects, or ``None`` when no files
        matched or the user cancelled the prompt.
    """
    if root is None:
        root = Path.cwd()

    matches = find_qmd_files(pattern, root, exclude_patterns)

    if not matches:
        logger.error(
            "No .qmd files matching '%s' found under %s",
            pattern, root,
        )
        return None

    if len(matches) == 1:
        return matches

    if not prompt:
        return matches

    # --- interactive selection -----------------------------------------------
    header = f"[{label}] " if label else ""
    print(f"\n{header}Multiple files match '{pattern}':\n")
    for i, p in enumerate(matches, 1):
        rel = p.relative_to(root)
        print(f"  {i}. {rel}")
    print(f"  a. All ({len(matches)} files)")
    hint = f"[{label}] " if label else ""
    print(f"  ({hint}enter = first match, or q to cancel)\n")

    while True:
        choice = input("Select: ").strip().lower()
        if not choice:
            return [matches[0]]
        if choice == "q":
            logger.info("Cancelled.")
            return None
        if choice == "a":
            return matches
        try:
            idx = int(choice) - 1
            if 0 <= idx < len(matches):
                return [matches[idx]]
        except ValueError:
            pass
        print(f"Invalid choice. Enter 1-{len(matches)}, 'a', or 'q'.")


def quick_render(
    pattern: str,
    root: Optional[Path] = None,
    format: Optional[str] = None,
    prompt: bool = True,
    label: Optional[str] = None,
    exclude_patterns: Optional[List[str]] = None,
) -> bool:
    """Locate .qmd files matching *pattern* and render them.

    This is a convenience wrapper that combines ``select_qmd_files`` and
    ``render_qmd`` into a single call.  For multi-pattern use (``sdb render
    kv id``) the CLI handler calls ``select_qmd_files`` directly to enable
    cross-pattern deduplication.

    Args:
        pattern:          Short name or path fragment.
        root:             Directory to search under.  Defaults to current
                          directory.
        format:           Optional output format passed to
                          ``quarto render --to``.
        prompt:           Whether to prompt on multiple matches.
        label:            Optional progress label prepended to the prompt
                          header (e.g. ``"1/3"``).  Ignored when *prompt*
                          is ``False``.
        exclude_patterns: Optional list of gitignore-style glob patterns
                          to exclude (loaded from ``build.yml``).

    Returns:
        ``True`` if every selected file rendered successfully.
    """
    selected = select_qmd_files(pattern, root, prompt, label, exclude_patterns)
    if selected is None:
        return False

    success = True
    for qmd in selected:
        if not render_qmd(qmd, cwd=root, format=format):
            success = False

    return success
