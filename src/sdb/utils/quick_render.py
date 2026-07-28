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

    # If pattern contains a path separator, search only the prioritized
    # directory subtree first. On first match, return immediately without
    # scanning the full tree.
    if "/" in pattern:
        dir_prefix = "/".join(pattern.split("/")[:-1])
        prio_dir = root / dir_prefix
        if prio_dir.exists():
            prio_candidates = sorted(prio_dir.rglob("*.qmd"))
            if exclude_patterns:
                from sdb.config import ConfigManager
                prio_candidates = [
                    p for p in prio_candidates
                    if not ConfigManager.matches_gitignore_pattern(
                        p.relative_to(root), exclude_patterns
                    )
                ]
            for p in prio_candidates:
                rel_str = str(p.relative_to(root).as_posix())
                if pattern in rel_str:
                    return [p]

    # Full tree scan (only reached when no prioritized match found)
    candidates: List[Path] = list(root.rglob("*.qmd"))

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
            rel = p.relative_to(root)
            rel_str = str(rel.as_posix())
            # Skip files under the already-searched prioritized directory
            dir_prefix = "/".join(pattern.split("/")[:-1])
            if rel_str.startswith(dir_prefix + "/"):
                continue
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


# ---------------------------------------------------------------------------
# resolve_and_render — full multi-pattern resolve + dedup + render pipeline
# ---------------------------------------------------------------------------


def resolve_and_render(
    patterns: list[str],
    root: Path,
    *,
    prompt: bool,
    exclude_patterns: Optional[list[str]] = None,
    format: Optional[str] = None,
) -> tuple[bool, list[Path]]:
    """Resolve patterns, deduplicate, render, and return results.

    This is the shared pipeline used by both ``sdb render`` and
    ``sdb pub``.

    Args:
        patterns:        List of short name / path fragment patterns.
        root:            Search root directory.
        prompt:          Whether to prompt on multi-match or duplicate.
        exclude_patterns: Patterns from ``build.yml``.
        format:          Output format passed to ``quarto render --to``.

    Returns:
        A tuple of ``(success, rendered_qmd_paths)`` where
        *rendered_qmd_paths* is the list of rendered QMD files
        (in original order, duplicates removed).
    """
    total = len(patterns)
    all_selected: list[tuple[Path, str]] = []
    n_ok = 0
    n_fail = 0

    for i, pattern in enumerate(patterns, 1):
        label = f"{i}/{total}" if total > 1 else None
        if label:
            logger.info("[%s] Pattern: %s", label, pattern)
        selected = select_qmd_files(
            pattern, root, prompt, label,
            exclude_patterns=exclude_patterns,
        )
        if selected is not None:
            n_ok += 1
            for p in selected:
                all_selected.append((p, pattern))
        else:
            n_fail += 1

    if not all_selected:
        return (False, [])

    # Deduplication
    file_to_patterns: dict[Path, list[str]] = {}
    file_order: list[Path] = []
    for p, pat in all_selected:
        if p not in file_to_patterns:
            file_to_patterns[p] = []
            file_order.append(p)
        file_to_patterns[p].append(pat)

    dup_map = {
        p: pats
        for p, pats in file_to_patterns.items()
        if len(pats) > 1
    }

    if dup_map and total > 1 and prompt:
        print(
            "\nThe following files were matched by more than one pattern:"
        )
        for p, pats in dup_map.items():
            rel = p.relative_to(root)
            print(f"  {rel}  ({', '.join(dict.fromkeys(pats))})")
        print()
        print("Choose how to handle duplicates:")
        print("  1. Render each file only once (skip duplicates)")
        print("  2. Render all (including duplicates)")
        print("  q. Cancel")

        while True:
            choice = input("\nSelect [1]: ").strip().lower()
            if not choice or choice == "1":
                all_selected = [(p, "") for p in file_order]
                break
            if choice == "2":
                break
            if choice == "q":
                logger.info("Cancelled.")
                return (False, [])
            print("Invalid choice. Enter 1, 2, or q.")

    # Render
    success = True
    for entry in all_selected:
        qmd = entry[0] if isinstance(entry, tuple) else entry
        if not render_qmd(qmd, cwd=root, format=format):
            success = False

    rendered_paths = list(dict.fromkeys(
        entry[0] if isinstance(entry, tuple) else entry
        for entry in all_selected
    ))

    if total > 1:
        logger.info(
            "Summary: %d of %d pattern(s) succeeded, %d failed. "
            "(%d unique file(s), %d render(s))",
            n_ok, total, n_fail,
            len(file_order), len(all_selected),
        )

    return (success, rendered_paths)


# ---------------------------------------------------------------------------
# publish_artifacts — collect PDF-related artifacts after rendering
# ---------------------------------------------------------------------------


def _collect_one(qmd_path: Path, dest: Path) -> list[Path]:
    """Copy PDF-related artifacts for a single rendered QMD into *dest*.

    Copies (when they exist):
      {stem}_files/figure-pdf/
      {stem}_files/mediabag/
      _files/
      {stem}.pdf
      {stem}.tex

    Returns the list of copied files/directories.
    """
    import shutil

    src_dir = qmd_path.parent
    stem = qmd_path.stem
    copied: list[Path] = []

    artifacts = [
        (src_dir / f"{stem}.pdf", dest / f"{stem}.pdf"),
    ]
    tex_path = src_dir / f"{stem}.tex"
    if tex_path.exists():
        artifacts.append((tex_path, dest / f"{stem}.tex"))

    dirs = [
        (src_dir / f"{stem}_files" / "figure-pdf", dest / f"{stem}_files" / "figure-pdf"),
        (src_dir / f"{stem}_files" / "mediabag", dest / f"{stem}_files" / "mediabag"),
        (src_dir / "_files", dest / "_files"),
    ]

    for src, dst in artifacts:
        if src.exists():
            dst.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(src, dst)
            copied.append(dst)
            logger.info("  Copied %s", dst)

    for src, dst in dirs:
        if src.exists() and src.is_dir():
            dst.parent.mkdir(parents=True, exist_ok=True)
            if dst.exists():
                shutil.rmtree(dst)
            shutil.copytree(src, dst)
            copied.append(dst)
            logger.info("  Copied %s", dst)

    return copied


def publish_artifacts(qmd_paths: list[Path]) -> int:
    """Collect PDF-related artifacts for rendered QMD files.

    For each rendered QMD, creates a folder named after the file's stem
    alongside the QMD file itself (e.g. ``kv.qmd`` → ``kv/``) and copies
    PDF-related artifacts into it preserving relative paths.

    Returns the total number of items copied.
    """
    total = 0
    for qmd in qmd_paths:
        stem = qmd.stem
        dest = qmd.parent / stem
        dest.mkdir(parents=True, exist_ok=True)
        logger.info("Publishing %s → %s", qmd, dest)
        n = len(_collect_one(qmd, dest))
        total += n
        if n == 0:
            logger.warning(
                "No PDF artifacts found for %s (was --to pdf used?)", qmd
            )
    return total
