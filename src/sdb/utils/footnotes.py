r"""Clean duplicate footnote reference tags in .qmd files.

Pandoc/Quarto markdown expects each footnote label to be referenced once
in the body.  Repeated uses of the same tag (for example ``[^tagma]``)
produce malformed output, so the default pre-build sequence removes
every use after the first.

Definitions (``[^label]: ...``), YAML front matter, fenced code blocks,
inline code spans, and escaped references (``\[^label]``) are left
untouched.
"""

from __future__ import annotations

import logging
import re
from pathlib import Path
from typing import List, Set, Tuple

import yaml

from sdb.utils.latest import matches_exclude

logger = logging.getLogger(__name__)

_FOOTNOTE_REF_RE = re.compile(r"\[\^([^\]]+)\]")
_FENCE_RE = re.compile(r"^\s*(`{3,}|~{3,})")
_SENTENCE_PUNCT = ".,;:!?"


def _code_span_ranges(line: str) -> List[Tuple[int, int]]:
    """Return ranges of text inside inline code spans in a single line.

    Backtick runs are paired sequentially: the text between an opening
    run and the next run is treated as code.  An unpaired trailing run
    protects the remainder of the line.
    """
    runs: List[Tuple[int, int]] = []
    i = 0
    n = len(line)
    while i < n:
        if line[i] == "`":
            j = i
            while j < n and line[j] == "`":
                j += 1
            runs.append((i, j))
            i = j
        else:
            i += 1

    ranges: List[Tuple[int, int]] = []
    k = 0
    while k + 1 < len(runs):
        ranges.append((runs[k][1], runs[k + 1][0]))
        k += 2
    if len(runs) % 2 == 1:
        ranges.append((runs[-1][1], len(line)))
    return ranges


def _is_escaped(line: str, pos: int) -> bool:
    """Return True when the bracket at ``pos`` is preceded by an odd
    number of backslashes."""
    backslashes = 0
    i = pos - 1
    while i >= 0 and line[i] == "\\":
        backslashes += 1
        i -= 1
    return backslashes % 2 == 1


def _is_definition(line: str, match: re.Match) -> bool:
    """Return True when ``match`` starts a footnote definition line.

    A definition is ``[^label]: ...`` with only whitespace before the
    opening bracket.
    """
    if line[: match.start()].strip(" \t"):
        return False
    return line[match.end():].startswith(":")


def _apply_removals(line: str, removals: List[Tuple[int, int]]) -> str:
    """Delete the given spans, consuming a preceding run of spaces.

    When the tag sits at the end of the line, before another space, or
    before sentence punctuation, the spaces before it are deleted as
    well so that no trailing or doubled spaces are left behind.
    """
    spans: List[Tuple[int, int]] = []
    for start, end in sorted(removals):
        following = ""
        if end < len(line) and line[end] not in "\r\n":
            following = line[end]
        if (
            start > 0
            and line[start - 1] == " "
            and (following in _SENTENCE_PUNCT or following in ("", " "))
        ):
            new_start = start
            while new_start > 0 and line[new_start - 1] == " ":
                new_start -= 1
            start = new_start
        if spans and start <= spans[-1][1]:
            spans[-1] = (spans[-1][0], max(spans[-1][1], end))
        else:
            spans.append((start, end))

    parts = []
    pos = 0
    for start, end in spans:
        parts.append(line[pos:start])
        pos = end
    parts.append(line[pos:])
    return "".join(parts)


def _process_line(line: str, seen: Set[str]) -> Tuple[str, int]:
    """Remove duplicate footnote references from one body line."""
    protected = _code_span_ranges(line)
    removals: List[Tuple[int, int]] = []
    for match in _FOOTNOTE_REF_RE.finditer(line):
        start, end = match.start(), match.end()
        if any(start >= s and end <= e for s, e in protected):
            continue
        if _is_escaped(line, start):
            continue
        if _is_definition(line, match):
            continue
        label = match.group(1)
        if label in seen:
            removals.append((start, end))
        else:
            seen.add(label)

    if not removals:
        return line, 0
    return _apply_removals(line, removals), len(removals)


def _closes_fence(line: str, fence_char: str) -> bool:
    """Return True when ``line`` is a closing fence of the given char."""
    return bool(re.match(r"^\s*" + re.escape(fence_char) + r"{3,}\s*$", line))


def strip_duplicate_footnote_refs(text: str) -> Tuple[str, int]:
    """Remove duplicate footnote reference tags from a .qmd document.

    Only the first use of each label in the body is kept.  Returns the
    cleaned text and the number of removed references.
    """
    seen: Set[str] = set()
    removed = 0
    lines = text.splitlines(keepends=True)

    in_front_matter = bool(
        lines and lines[0].lstrip("\ufeff").strip() == "---"
    )
    fence_char: str | None = None
    out_lines: List[str] = []

    for index, line in enumerate(lines):
        if in_front_matter:
            out_lines.append(line)
            if index > 0 and line.strip() == "---":
                in_front_matter = False
            continue

        if fence_char is not None:
            out_lines.append(line)
            if _closes_fence(line, fence_char):
                fence_char = None
            continue

        fence_match = _FENCE_RE.match(line)
        if fence_match:
            fence_char = fence_match.group(1)[0]
            out_lines.append(line)
            continue

        cleaned, n = _process_line(line, seen)
        removed += n
        out_lines.append(cleaned)

    return "".join(out_lines), removed


def _load_build_yml_excludes(docs_root: Path) -> List[str]:
    """Return the ``exclude:`` patterns from ``build.yml``, if present."""
    config_path = docs_root / "build.yml"
    if not config_path.is_file():
        return []
    try:
        cfg = yaml.safe_load(config_path.read_text(encoding="utf-8")) or {}
        extra = cfg.get("exclude", [])
        if isinstance(extra, list):
            return [p for p in extra if isinstance(p, str)]
    except Exception:
        logger.warning("Could not read exclude patterns from %s", config_path)
    return []


def _discover_qmd_files(docs_root: Path, exclude_patterns: List[str]) -> List[Path]:
    files = []
    for path in sorted(docs_root.rglob("*.qmd")):
        rel = path.relative_to(docs_root).as_posix()
        if matches_exclude(rel, exclude_patterns):
            continue
        files.append(path)
    return files


def clean_duplicate_footnotes(docs_root: Path) -> bool:
    """Remove duplicate footnote reference tags from all .qmd files.

    Runs as part of the default pre-build sequence.  For each .qmd file
    under ``docs_root`` (respecting build.yml ``exclude:`` patterns and
    system-ignored directories), every footnote reference after the first
    use of its label is removed.

    Returns True on success.
    """
    exclude_patterns = _load_build_yml_excludes(docs_root)
    files = _discover_qmd_files(docs_root, exclude_patterns)
    if not files:
        logger.info("Footnote cleanup: no .qmd files to process.")
        return True

    total_removed = 0
    modified = 0
    for qmd in files:
        try:
            original = qmd.read_text(encoding="utf-8")
        except (OSError, UnicodeDecodeError) as exc:
            logger.warning("Footnote cleanup: could not read %s: %s", qmd, exc)
            continue
        cleaned, removed = strip_duplicate_footnote_refs(original)
        if not removed:
            continue
        try:
            qmd.write_text(cleaned, encoding="utf-8")
        except OSError as exc:
            logger.warning("Footnote cleanup: could not write %s: %s", qmd, exc)
            continue
        total_removed += removed
        modified += 1
        logger.info(
            "Footnote cleanup: removed %d duplicate reference(s) from %s",
            removed, qmd.relative_to(docs_root),
        )

    if modified:
        logger.info(
            "Footnote cleanup: removed %d duplicate reference(s) from %d file(s).",
            total_removed, modified,
        )
    else:
        logger.info("Footnote cleanup: no duplicate footnote references found.")
    return True
