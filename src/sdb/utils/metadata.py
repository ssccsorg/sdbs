r"""Generate the LaTeX metadata file a document's title page consumes.

The title page is assembled from a generated ``_metadata.tex`` that
declares the version, author, and affiliation macros.  A document
references that file from its own front matter::

    format:
      pdf:
        include-in-header:
          text: |
            \input{./_files/<name>_metadata.tex}

The reference is the discovery key.  The step generates exactly the path
the document asks for and nothing else, which is what lets it run before
every build without touching a file a person owns.

Holding the generation here makes it part of the default pre-build
sequence, so a project no longer has to ship
``_include/_generate_metadata_tex.py`` and wire a Quarto ``pre-render``
hook for the file to exist.  ``src/sdb/templates/advanced/`` keeps its
copy for projects rendered by Quarto alone; the macro list below is the
one both are expected to write.

Two rules keep the step free of side effects.

- It writes only a path a document references, only inside the docs root,
  and never edits a document or a Quarto configuration.
- It writes only when the target is missing or older than the document
  and the files the document resolves through ``metadata-files``.  A
  repeated run converges after the first pass, and a project hook that
  writes the same path at render time stays quiet because its output is
  newer than the document.
"""

from __future__ import annotations

import hashlib
import logging
import re
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, Iterable, List, Tuple

import yaml

from sdb.utils.latest import matches_exclude

logger = logging.getLogger(__name__)

METADATA_INPUT_RE = re.compile(r"\\input\{([^}]*_metadata\.tex)\}")

_ESCAPE_MAP = {
    "&": r"\&",
    "%": r"\%",
    "$": r"\$",
    "#": r"\#",
    "_": r"\_",
    "{": r"\{",
    "}": r"\}",
    "~": r"\textasciitilde{}",
    "^": r"\textasciicircum{}",
}

# The macros the generated file declares.  A document whose front matter
# names one of these needs the file to exist.
GENERATED_MACROS: Tuple[str, ...] = (
    "version",
    "timestamp",
    "affiliationname",
    "affiliationurl",
    "affiliationdomain",
    "authorname",
    "authoremail",
    "authorrole",
    "orcid",
    "filehash",
)

_VERSION_MARK_BLOCK = (
    "\n"
    "\\usepackage{xcolor}\n"
    "\\usepackage{graphicx}\n"
    "\\usepackage{background}\n"
    "\\backgroundsetup{\n"
    "    contents={\\rotatebox{90}{\\ttfamily\\color{lightgray}\\version}},\n"
    "        angle=0,\n"
    "        scale=1,\n"
    "        opacity=1,\n"
    "        position=current page.east,\n"
    "        vshift=0pt,\n"
    "        hshift=-20pt\n"
    "}\n"
    "\n"
)


def _read_text(path: Path) -> str:
    try:
        return path.read_text(encoding="utf-8")
    except (OSError, UnicodeDecodeError) as exc:
        logger.warning("Metadata: could not read %s: %s", path, exc)
        return ""


def _preceded_by_backslash(value: str, index: int) -> bool:
    """Return True when the character at ``index`` follows an odd run of backslashes."""
    count = 0
    i = index - 1
    while i >= 0 and value[i] == "\\":
        count += 1
        i -= 1
    return count % 2 == 1


def escape_value(value: str) -> str:
    """Escape LaTeX specials in an author value, leaving existing escapes alone.

    The author data in the corpus disagrees about where escaping happens:
    some trees store a raw ``&`` and rely on the writer, and others store
    ``\\&`` already escaped.  An unconditional escape turns the second
    case into ``\\textbackslash{}\\&`` and renders a stray backslash, so a
    character that already follows a backslash passes through.
    """
    out = []
    for index, char in enumerate(value):
        if char in _ESCAPE_MAP and not _preceded_by_backslash(value, index):
            out.append(_ESCAPE_MAP[char])
        else:
            out.append(char)
    return "".join(out)


def front_matter_text(text: str) -> str:
    """Return the raw YAML front matter block of a document.

    The raw text is kept alongside the parsed mapping because the
    reference to the generated file and the macro names a title override
    uses are examined as text, and because a document with invalid YAML
    should still be reported rather than silently skipped.
    """
    lines = text.splitlines(keepends=True)
    if not lines or lines[0].lstrip("\ufeff").strip() != "---":
        return ""
    for index in range(1, len(lines)):
        if lines[index].strip() == "---":
            return "".join(lines[1:index])
    return ""


def read_front_matter(qmd_path: Path) -> Dict[str, Any]:
    """Parse the YAML front matter of a document, or return an empty mapping."""
    block = front_matter_text(_read_text(qmd_path))
    if not block:
        return {}
    try:
        data = yaml.safe_load(block)
    except yaml.YAMLError as exc:
        logger.warning("Metadata: invalid front matter in %s: %s", qmd_path, exc)
        return {}
    return data if isinstance(data, dict) else {}


def find_metadata_inputs(front_matter_block: str) -> List[str]:
    """Return the ``..._metadata.tex`` paths the front matter references."""
    return [m.group(1) for m in METADATA_INPUT_RE.finditer(front_matter_block)]


def named_contract_macros(front_matter_block: str) -> List[str]:
    """Return the generated macros the front matter names, in declaration order."""
    return [
        name
        for name in GENERATED_MACROS
        if re.search(r"\\" + name + r"\b", front_matter_block)
    ]


def resolve_metadata_files(
    front: Dict[str, Any], qmd_path: Path
) -> Tuple[Dict[str, Any], List[Path]]:
    """Merge the ``metadata-files`` chain over the front matter.

    Files apply in declaration order, so a later file overrides an
    earlier one, and the document's own front matter has the final say.
    Returns the merged mapping and the files that existed, which the
    freshness test needs because a change to any of them can change the
    generated macros.
    """
    merged: Dict[str, Any] = {}
    sources: List[Path] = []

    declared = front.get("metadata-files")
    if isinstance(declared, list):
        for entry in declared:
            if not isinstance(entry, str):
                continue
            candidate = (qmd_path.parent / entry).resolve()
            if not candidate.is_file():
                logger.warning(
                    "Metadata: %s lists missing metadata file %s",
                    qmd_path.name, entry,
                )
                continue
            try:
                data = yaml.safe_load(candidate.read_text(encoding="utf-8")) or {}
            except (OSError, UnicodeDecodeError, yaml.YAMLError) as exc:
                logger.warning("Metadata: could not read %s: %s", candidate, exc)
                continue
            if isinstance(data, dict):
                merged.update(data)
            sources.append(candidate)

    merged.update(front)
    return merged, sources


def _first_author(merged: Dict[str, Any]) -> Dict[str, Any]:
    authors = merged.get("author")
    if isinstance(authors, list) and authors and isinstance(authors[0], dict):
        return authors[0]
    return {}


def _first_affiliation(author: Dict[str, Any]) -> Dict[str, Any]:
    affiliations = author.get("affiliations")
    if (
        isinstance(affiliations, list)
        and affiliations
        and isinstance(affiliations[0], dict)
    ):
        return affiliations[0]
    return {}


def render_metadata_tex(merged: Dict[str, Any], qmd_path: Path) -> str:
    """Render the macro declarations a document's version and title page need.

    The version string carries the document hash, so the stamp identifies
    the revision of the text the render used.
    """
    file_hash = hashlib.sha256(qmd_path.read_bytes()).hexdigest()
    date_short = datetime.now().strftime("%y%m%d")
    prefix = merged.get("version-prefix")
    if prefix is not None:
        version_str = f"{prefix}-{file_hash[:6]}-{date_short}"
    else:
        version_str = f"{file_hash[:6]}-{date_short}"

    author = _first_author(merged)
    affiliation = _first_affiliation(author)

    values = {
        "affiliationname": affiliation.get("name", ""),
        "affiliationurl": affiliation.get("url", ""),
        "affiliationdomain": affiliation.get("domain", ""),
        "authorname": author.get("name", ""),
        "authoremail": author.get("email", ""),
        "authorrole": author.get("role", ""),
        "orcid": author.get("orcid", ""),
    }

    lines = [
        f"\\newcommand{{\\version}}{{{escape_value(version_str)}}}\n",
        f"\\newcommand{{\\timestamp}}{{{datetime.now()}}}\n",
    ]
    for name, value in values.items():
        lines.append(
            f"\\newcommand{{\\{name}}}{{{escape_value(str(value))}}}\n"
        )
    lines.append(f"\\newcommand{{\\filehash}}{{{file_hash}}}\n")

    if merged.get("version-mark"):
        lines.append(_VERSION_MARK_BLOCK)

    return "".join(lines)


def _display(path: Path, root: Path) -> str:
    """Return a path for logging, tolerating one outside the root."""
    try:
        return str(path.relative_to(root))
    except ValueError:
        return str(path)


def _newest_mtime(paths: List[Path]) -> float:
    stamps = []
    for path in paths:
        try:
            stamps.append(path.stat().st_mtime)
        except OSError:
            continue
    return max(stamps) if stamps else 0.0


def _is_stale(target: Path, inputs: List[Path]) -> bool:
    try:
        target_mtime = target.stat().st_mtime
    except OSError:
        return True
    return target_mtime < _newest_mtime(inputs)


def generate_metadata_tex(docs_root: Path) -> bool:
    """Generate every ``_metadata.tex`` a document under the root references.

    Runs as the last step of the default pre-build sequence, so the
    version stamp covers the text after path resolution and formatting.
    """
    root = docs_root.resolve()
    return _generate(
        root, _discover_qmd_files(root, _load_build_yml_excludes(root))
    )


def generate_metadata_for(qmd_paths: Iterable[Path], docs_root: Path) -> bool:
    """Generate the metadata files the given documents reference.

    The preview commands render a named document without running the
    pre-build sequence, so they call this directly.
    """
    root = docs_root.resolve()
    return _generate(root, sorted(Path(path) for path in qmd_paths))


def _generate(root: Path, qmds: Iterable[Path]) -> bool:
    """Write the metadata file of every given document that needs one.

    Returns True on success; a document that cannot be served is reported
    and left alone.
    """
    claimed: Dict[Path, Path] = {}
    written = 0
    missing_reference = 0

    for qmd in qmds:
        qmd = Path(qmd).resolve()
        text = _read_text(qmd)
        block = front_matter_text(text)
        references = find_metadata_inputs(block)

        if not references:
            used = named_contract_macros(block)
            if used:
                missing_reference += 1
                logger.warning(
                    "Metadata: %s names %s with no \\input{..._metadata.tex} "
                    "reference, so the generated file has no path into the "
                    "document.",
                    _display(qmd, root), ", ".join(used),
                )
            continue

        front = read_front_matter(qmd)
        merged, sources = resolve_metadata_files(front, qmd)

        for reference in references:
            target = (qmd.parent / reference).resolve()
            if not target.is_relative_to(root):
                logger.warning(
                    "Metadata: %s references %s outside the docs root, skipping.",
                    _display(qmd, root), reference,
                )
                continue
            owner = claimed.get(target)
            if owner is not None and owner != qmd:
                logger.warning(
                    "Metadata: %s and %s both reference %s, leaving it to %s.",
                    _display(owner, root), _display(qmd, root),
                    reference, _display(owner, root),
                )
                continue
            claimed[target] = qmd

            inputs = [qmd] + sources
            if not _is_stale(target, inputs):
                continue

            try:
                target.parent.mkdir(parents=True, exist_ok=True)
                target.write_text(render_metadata_tex(merged, qmd), encoding="utf-8")
            except OSError as exc:
                logger.warning("Metadata: could not write %s: %s", target, exc)
                continue

            written += 1
            logger.info(
                "Metadata: wrote %s for %s",
                _display(target, root), _display(qmd, root),
            )

    if written:
        logger.info("Metadata: generated %d file(s).", written)
    else:
        logger.info("Metadata: no file needs regenerating.")
    if missing_reference:
        logger.info(
            "Metadata: %d document(s) name a metadata macro without a reference.",
            missing_reference,
        )
    return True


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
    files: List[Path] = []
    for path in sorted(docs_root.rglob("*.qmd")):
        rel = path.relative_to(docs_root).as_posix()
        if matches_exclude(rel, exclude_patterns):
            continue
        files.append(path)
    return files
