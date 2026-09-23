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

- It writes only what a document's own declarations ask for, and only inside
  the docs root.  It generates the path a document references, inserts the
  reference a header needs but does not declare, which is the inconsistency
  that would otherwise reach LuaLaTeX as an undefined control sequence, and
  adds the affiliation keys an ``affiliations`` entry is missing.  Every write
  adds to a file the document already names, and a Quarto configuration is
  never edited.
- It writes the generated file only when the target is missing or older than
  the document and the files the document resolves through
  ``metadata-files``.  A repeated run converges after the first pass, and a
  project hook that writes the same path at render time stays quiet because
  its output is newer than the document.

Two differences from the per-project ``_generate_metadata_tex.py`` scripts
remain.  Neither changes a document in the corpus today.

- A file referenced by several documents is written from the first of them
  in path order and the choice is reported at info level, while a project
  hook writes it from whichever document rendered last.  Sharing is normal
  here: five ssccs philosophy documents and three es documents point at one
  file each, and ``mtep/_files/_metadata.tex`` is shared by two documents
  that disagree about ``version-mark``.
- ``version-prefix`` and ``version-mark`` are read from the merged metadata,
  so a project could set them in a shared ``metadata-files`` entry.  The
  generator scripts read only the document's own front matter, and no
  project in the corpus uses the shared form.

The contract is the macro list below.  A header is examined for those names
and for the reference that gives them a path into the document, and for
nothing else.  A command the generator does not declare, and a name outside
the list, are not this step's to judge, so a header that names only such a
name passes in silence.  The step is a statement about the metadata contract,
and not about a document's LaTeX.
"""

from __future__ import annotations

import hashlib
import logging
import re
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, Iterable, List, Optional, Tuple
from urllib.parse import urlparse

import yaml

from sdb.utils.latest import matches_exclude

logger = logging.getLogger(__name__)

METADATA_NAME_RE = re.compile(r"_metadata\.tex$")
INPUT_RE = re.compile(r"\\input\{([^}]+)\}")

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


def _matching_brace(value: str, start: int) -> Optional[int]:
    """Return the index of the brace that closes the one at ``start``."""
    depth = 0
    for index in range(start, len(value)):
        if value[index] == "{":
            depth += 1
        elif value[index] == "}":
            depth -= 1
            if depth == 0:
                return index
    return None


def _command_end(value: str, start: int) -> int:
    r"""Return the index after a LaTeX command beginning at ``start``.

    Returns ``start`` when the backslash opens no command name, so a bare
    ``\&`` or ``\{`` is handled by the escape rule below.  A command that
    carries a braced argument is consumed with it, which keeps a value such
    as ``\textbackslash{}`` from having its braces escaped apart from the
    command that needs them.
    """
    index = start + 1
    if index >= len(value) or not value[index].isalpha():
        return start
    while index < len(value) and value[index].isalpha():
        index += 1
    if index < len(value) and value[index] == "{":
        end = _matching_brace(value, index)
        if end is not None:
            return end + 1
    return index


def escape_value(value: str) -> str:
    """Escape LaTeX specials in an author value, leaving existing LaTeX alone.

    The author data in the corpus disagrees about where escaping happens:
    some trees store a raw ``&`` and rely on the writer, and others store
    ``\\&`` already escaped.  An unconditional escape turns the second
    case into ``\\textbackslash{}\\&`` and renders a stray backslash, so a
    value that already carries a LaTeX command passes through untouched.
    """
    out = []
    index = 0
    while index < len(value):
        char = value[index]
        if char == "\\":
            end = _command_end(value, index)
            if end > index:
                out.append(value[index:end])
                index = end
                continue
        if char in _ESCAPE_MAP and not _preceded_by_backslash(value, index):
            out.append(_ESCAPE_MAP[char])
        else:
            out.append(char)
        index += 1
    return "".join(out)


# ---------------------------------------------------------------------------
# Case inventory
# ---------------------------------------------------------------------------
# Every potential inconsistency between a document's declarations and what the
# renderer needs is one named case.  A case reports, and repairs when the
# repair is mechanical.  The order below is the order they run, and each
# position is an ordering constraint rather than a preference:
#
#   1. document-outside-root            report.  Nothing else can be judged.
#   2. input-missing                    report.  Needs the document text.
#   3. reference-missing                repair, insert the \input line, and
#      report when no line can be added.  It decides whether a file is
#      generated at all, and it changes the document text the version stamp
#      hashes, so it runs before the stamp is taken.
#   4. invalid-front-matter             report.  Needs the parsed mapping.
#   5. declared-metadata-missing        report.  Needs the parsed mapping.
#   6. affiliation-url-from-author-key  repair, the url is declared elsewhere.
#   7. affiliation-url-from-domain      repair, https://<domain>.
#   8. affiliation-domain-from-url      repair, the netloc of the url.
#   9. affiliation-blank                report.  Nothing is left to derive from.
#  10. reference-outside-root           report.  Needs the claimed set.
#  11. shared-target                    report.  Needs the claimed set.
#  12. metadata-file-missing-or-stale   repair, write the generated file.  It
#      runs last because the cases above change what it must contain.
#
# A case can be turned off by name under ``metadata.disabled`` in build.yml,
# and every repair can be turned off at once with ``metadata.report_only``,
# which leaves the step reading and reporting only (the default sequence's
# steps are documented in the README).
CASE_DOCUMENT_OUTSIDE_ROOT = "document-outside-root"
CASE_INPUT_MISSING = "input-missing"
CASE_REFERENCE_MISSING = "reference-missing"
CASE_INVALID_FRONT_MATTER = "invalid-front-matter"
CASE_DECLARED_METADATA_MISSING = "declared-metadata-missing"
CASE_AFFILIATION_URL_FROM_AUTHOR_KEY = "affiliation-url-from-author-key"
CASE_AFFILIATION_URL_FROM_DOMAIN = "affiliation-url-from-domain"
CASE_AFFILIATION_DOMAIN_FROM_URL = "affiliation-domain-from-url"
CASE_AFFILIATION_BLANK = "affiliation-blank"
CASE_REFERENCE_OUTSIDE_ROOT = "reference-outside-root"
CASE_SHARED_TARGET = "shared-target"
CASE_METADATA_FILE = "metadata-file-missing-or-stale"

CASE_ORDER: Tuple[str, ...] = (
    CASE_DOCUMENT_OUTSIDE_ROOT,
    CASE_INPUT_MISSING,
    CASE_REFERENCE_MISSING,
    CASE_INVALID_FRONT_MATTER,
    CASE_DECLARED_METADATA_MISSING,
    CASE_AFFILIATION_URL_FROM_AUTHOR_KEY,
    CASE_AFFILIATION_URL_FROM_DOMAIN,
    CASE_AFFILIATION_DOMAIN_FROM_URL,
    CASE_AFFILIATION_BLANK,
    CASE_REFERENCE_OUTSIDE_ROOT,
    CASE_SHARED_TARGET,
    CASE_METADATA_FILE,
)

# A URL is derived with this scheme when only a domain is declared.  Every
# affiliation in the corpus uses it, and the case is separately switchable.
DERIVED_URL_SCHEME = "https://"


@dataclass(frozen=True)
class MetadataPolicy:
    """Which cases may repair, and which are off entirely."""

    report_only: bool = False
    disabled: Tuple[str, ...] = ()

    def is_enabled(self, case: str) -> bool:
        return case not in self.disabled

    def may_repair(self, case: str) -> bool:
        return self.is_enabled(case) and not self.report_only


def load_metadata_policy(docs_root: Path) -> MetadataPolicy:
    """Read the ``metadata:`` block from ``build.yml``.

    Unknown case names are reported rather than ignored, so a typo in a
    switch does not silently leave a case on.
    """
    config_path = docs_root / "build.yml"
    if not config_path.is_file():
        return MetadataPolicy()
    try:
        cfg = yaml.safe_load(config_path.read_text(encoding="utf-8")) or {}
    except (OSError, UnicodeDecodeError, yaml.YAMLError):
        logger.warning("Could not read metadata policy from %s", config_path)
        return MetadataPolicy()
    block = cfg.get("metadata") if isinstance(cfg, dict) else None
    if not isinstance(block, dict):
        return MetadataPolicy()

    disabled = block.get("disabled", [])
    names = tuple(name for name in disabled if isinstance(name, str)) \
        if isinstance(disabled, list) else ()
    unknown = [name for name in names if name not in CASE_ORDER]
    if unknown:
        logger.warning(
            "Unknown metadata case name(s) in build.yml: %s. Known cases: %s",
            ", ".join(unknown), ", ".join(CASE_ORDER),
        )
    return MetadataPolicy(
        report_only=bool(block.get("report_only", False)),
        disabled=names,
    )


def _note(case: str, detail: str, level: int = logging.WARNING) -> None:
    """Log one finding, tagged with the case that produced it."""
    logger.log(level, "Metadata[%s]: %s", case, detail)


def _did(case: str, detail: str) -> None:
    """Log one repair, tagged with the case that produced it."""
    logger.info("Metadata[%s]: %s (FIXING)", case, detail)


# ---------------------------------------------------------------------------
# Affiliation declaration
# ---------------------------------------------------------------------------
# The title page links with \href{\affiliationurl}{\affiliationdomain}, so an
# affiliation that declares neither links nowhere.  An empty link is not a
# LaTeX error, which is why this case reports rather than failing: the
# declaration is incomplete for its consumer, and it is the generated file that
# carries the result.
#
# A supplied key goes into the declared file rather than into the generated
# one, because the declared file is what the generator reads: a Quarto-only
# render, which reads the same file, is healed by the same write.
#
# A case fires only for a macro the document's own header names, so a document
# that does not link an affiliation is never the reason a declared file is
# edited.
_AFFILIATION_URL_MACRO = "affiliationurl"
_AFFILIATION_DOMAIN_MACRO = "affiliationdomain"

# The key a legacy author file may carry the affiliation url under, beside the
# nested affiliations entry the generator reads.
_AUTHOR_URL_KEYS = ("affiliation-url", "affiliation_url")

_LIST_ITEM_RE = re.compile(r"^(?P<indent>\s*)-\s(?P<rest>\S.*)$")
_AFFILIATIONS_RE = re.compile(r"^\s*affiliations:\s*$")


def _declared(value: Any) -> Optional[str]:
    """Return the trimmed string a mapping declares, or None."""
    if isinstance(value, str) and value.strip():
        return value.strip()
    return None


def derive_affiliation_url(
    author: Dict[str, Any], affiliation: Dict[str, Any]
) -> Tuple[Optional[str], Optional[str]]:
    """Return the url to supply for an affiliation that declares none.

    Returns ``(url, case)``, or ``(None, None)`` when the affiliation
    declares a url or when nothing here can be derived from it.
    """
    if _declared(affiliation.get("url")):
        return None, None
    for key in _AUTHOR_URL_KEYS:
        candidate = _declared(author.get(key))
        if candidate:
            return candidate, CASE_AFFILIATION_URL_FROM_AUTHOR_KEY
    domain = _declared(affiliation.get("domain"))
    if domain:
        return DERIVED_URL_SCHEME + domain, CASE_AFFILIATION_URL_FROM_DOMAIN
    return None, None


def derive_affiliation_domain(
    affiliation: Dict[str, Any], url: Optional[str]
) -> Tuple[Optional[str], Optional[str]]:
    """Return the domain to supply for an affiliation that declares none."""
    if _declared(affiliation.get("domain")):
        return None, None
    candidate = _declared(url) or _declared(affiliation.get("url"))
    if not candidate:
        return None, None
    netloc = urlparse(candidate).netloc
    if netloc:
        return netloc, CASE_AFFILIATION_DOMAIN_FROM_URL
    return None, None


def _affiliation_item(lines: List[str]) -> Optional[Tuple[int, int, int]]:
    """Locate the first item of the first ``affiliations`` list.

    Returns ``(item index, last index, key indentation)`` so a supplied key
    can be appended to the item with the indentation its siblings use.
    """
    start = None
    for index, line in enumerate(lines):
        if _AFFILIATIONS_RE.match(line.rstrip("\n")):
            start = index
            break
    if start is None:
        return None

    cursor = start + 1
    while cursor < len(lines) and not lines[cursor].strip():
        cursor += 1
    if cursor >= len(lines):
        return None
    match = _LIST_ITEM_RE.match(lines[cursor].rstrip("\n"))
    if not match:
        return None

    item = cursor
    indent = len(match.group("indent"))
    key_indent = indent + 2
    last = item
    cursor = item + 1
    while cursor < len(lines):
        current = lines[cursor].rstrip("\n")
        if not current.strip():
            break
        if len(current) - len(current.lstrip()) <= indent:
            break
        last = cursor
        cursor += 1
    return item, last, key_indent


def _item_key(
    lines: List[str], item: int, last: int, key: str
) -> Tuple[bool, Optional[str]]:
    """Return ``(declared, value)`` for ``key`` inside a list item."""
    pattern = re.compile(r"^\s*" + re.escape(key) + r":\s*(?P<value>.*)$")
    for index in range(item, last + 1):
        match = pattern.match(lines[index].rstrip("\n"))
        if match:
            return True, match.group("value").strip()
    return False, None


def supply_affiliation_declaration(
    path: Path, used_macros: Iterable[str], policy: MetadataPolicy, root: Path
) -> bool:
    """Add the affiliation keys a title page links with to a declared file.

    Only a key for a macro the document names is considered, only a key the
    item does not already declare is added, at the indentation its siblings
    use, and nothing else in the file changes.  Returns whether the file
    changed, which tells the caller the merged mapping has to be read again.
    """
    text = _read_text(path)
    try:
        data = yaml.safe_load(text)
    except yaml.YAMLError as exc:
        logger.warning("Metadata: could not read %s: %s", path, exc)
        return False
    if not isinstance(data, dict):
        return False

    author = _first_author(data)
    affiliation = _first_affiliation(author)
    if not affiliation:
        return False

    url, url_case = derive_affiliation_url(author, affiliation)
    # A domain derived from a url is derived from the url the file will carry,
    # so switching the url case off leaves the two in step rather than writing
    # a domain beside a url that is not there.
    effective_url = affiliation.get("url")
    if url is not None and policy.may_repair(url_case):
        effective_url = url
    domain, domain_case = derive_affiliation_domain(affiliation, effective_url)
    supplied = (
        (_AFFILIATION_URL_MACRO, "url", url, url_case),
        (_AFFILIATION_DOMAIN_MACRO, "domain", domain, domain_case),
    )
    used = set(used_macros)
    if not any(macro in used and value is not None for macro, _, value, _ in supplied):
        return False

    lines = text.splitlines(keepends=True)
    located = _affiliation_item(lines)
    if located is None:
        return False
    item, last, key_indent = located

    added = []
    for macro, key, value, case in supplied:
        if macro not in used or value is None:
            continue
        if not policy.may_repair(case):
            continue
        present, _ = _item_key(lines, item, last, key)
        if present:
            continue
        lines.insert(last + 1, " " * key_indent + f"{key}: {value}\n")
        last += 1
        added.append((case, key, value))

    if not added:
        return False
    try:
        path.write_text("".join(lines), encoding="utf-8")
    except OSError as exc:
        logger.warning("Metadata: could not write %s: %s", path, exc)
        return False
    for case, key, value in added:
        _did(case, f"{_display(path, root)}: added {key}: {value}")
    return True


def report_affiliation_gaps(
    merged: Dict[str, Any],
    used_macros: Iterable[str],
    qmd: Path,
    root: Path,
    policy: MetadataPolicy,
) -> None:
    """Report an affiliation link the header cannot fill.

    The header is what consumes the values, so a gap is reported only for a
    macro the header actually names: an affiliation that declares no url in a
    document that links no url is not a mismatch.
    """
    if not policy.is_enabled(CASE_AFFILIATION_BLANK):
        return
    affiliation = _first_affiliation(_first_author(merged))
    if not affiliation:
        return

    used = set(used_macros)
    gaps = []
    if _AFFILIATION_URL_MACRO in used and not _declared(affiliation.get("url")):
        gaps.append("url")
    if _AFFILIATION_DOMAIN_MACRO in used and not _declared(
        affiliation.get("domain")
    ):
        gaps.append("domain")
    if not gaps:
        return
    named = "/".join(f"\\affiliation{gap}" for gap in gaps)
    _note(
        CASE_AFFILIATION_BLANK,
        f"{_display(qmd, root)} links {named}, and its affiliation declares "
        f"no {' or '.join(gaps)}.",
    )


def _front_matter_end(lines: List[str]) -> Optional[int]:
    """Return the index of the line that closes the front matter."""
    if not lines or lines[0].lstrip("\ufeff").strip() != "---":
        return None
    for index in range(1, len(lines)):
        if lines[index].strip() == "---":
            return index
    return None


def front_matter_text(text: str) -> str:
    """Return the raw YAML front matter block of a document.

    The raw text is kept alongside the parsed mapping because the
    reference to the generated file and the macro names a title override
    uses are examined as text, and because a document with invalid YAML
    should still be reported rather than silently skipped.
    """
    lines = text.splitlines(keepends=True)
    end = _front_matter_end(lines)
    if end is None:
        return ""
    return "".join(lines[1:end])


def parse_front_matter(text: str) -> Optional[Dict[str, Any]]:
    """Parse the front matter of a document.

    Returns an empty mapping when the document declares none, and None when
    the block is present but invalid.  The distinction matters: a caller
    that would otherwise write declarations from the data has to stop
    rather than write a file of empty macros.
    """
    block = front_matter_text(text)
    if not block:
        return {}
    try:
        data = yaml.safe_load(block)
    except yaml.YAMLError:
        return None
    return data if isinstance(data, dict) else {}


def find_inputs(front_matter_block: str) -> List[str]:
    """Return every file the front matter inputs."""
    return [m.group(1) for m in INPUT_RE.finditer(front_matter_block)]


def find_metadata_inputs(front_matter_block: str) -> List[str]:
    """Return the inputs whose name follows the generated-file convention.

    The name is the discovery key, so a document that asks for
    ``./_files/meta.tex`` is served by nothing.  ``find_inputs`` exists so
    that case can still be reported.
    """
    return [
        path for path in find_inputs(front_matter_block)
        if METADATA_NAME_RE.search(path)
    ]


def named_contract_macros(front_matter_block: str) -> List[str]:
    """Return the generated macros the front matter names, in declaration order."""
    return [
        name
        for name in GENERATED_MACROS
        if re.search(r"\\" + name + r"\b", front_matter_block)
    ]


_HEADER_TEXT_RE = re.compile(r"^(?P<indent>\s*)text:\s*\|[-+]?\s*$")


def _header_block_starts(lines: List[str]) -> List[Tuple[int, int]]:
    """Locate the literal header blocks that name a generated macro.

    Returns ``(first content line index, content indentation)`` for every
    ``text: |`` block whose content uses a macro, so a missing reference
    can be added where the macros are used rather than anywhere in the
    front matter.
    """
    found: List[Tuple[int, int]] = []
    for index, line in enumerate(lines):
        match = _HEADER_TEXT_RE.match(line)
        if not match:
            continue
        directive_indent = len(match.group("indent"))
        if index + 1 >= len(lines):
            continue
        first = lines[index + 1]
        if not first.strip():
            continue
        content_indent = len(first) - len(first.lstrip())
        if content_indent <= directive_indent:
            continue

        block: List[str] = []
        cursor = index + 1
        while cursor < len(lines):
            current = lines[cursor]
            if current.strip() and (len(current) - len(current.lstrip())) <= directive_indent:
                break
            block.append(current)
            cursor += 1

        body = "".join(block)
        if any(re.search(r"\\" + name + r"\b", body) for name in GENERATED_MACROS):
            found.append((index + 1, content_indent))
    return found


def insert_reference(text: str, reference: str) -> Optional[str]:
    """Add an ``\\input`` for the generated file to the header that needs it.

    The line goes at the front of every literal header block that names a
    generated macro, indented to match the block, and nowhere else.  Returns
    None when the document offers no block that can be edited mechanically,
    which leaves the choice to the author.
    """
    lines = text.splitlines(keepends=True)
    end = _front_matter_end(lines)
    if end is None:
        return None

    starts = _header_block_starts(lines[:end])
    if not starts:
        return None

    for index, indent in reversed(starts):
        lines.insert(index, " " * indent + f"\\input{{{reference}}}\n")
    return "".join(lines)


def metadata_reference_for(qmd_path: Path) -> str:
    """Return the generated file path a document is given by convention.

    One file per document, so a directory whose documents share a header
    does not end up sharing one generated file.
    """
    return f"./_files/{qmd_path.stem}_metadata.tex"


def resolve_metadata_files(
    front: Dict[str, Any],
    qmd_path: Path,
    policy: MetadataPolicy = MetadataPolicy(),
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
                if policy.is_enabled(CASE_DECLARED_METADATA_MISSING):
                    _note(
                        CASE_DECLARED_METADATA_MISSING,
                        f"{qmd_path.name} lists missing metadata file {entry}",
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


def _repair_missing_reference(qmd: Path, text: str) -> Optional[str]:
    """Add the reference a header needs but the document does not declare.

    A header that uses a generated macro with no ``\\input`` line is the
    inconsistency that reaches LuaLaTeX as an undefined control sequence.
    The repair is confined to a document that asks for the contract and
    carries no other input this step cannot account for, so a document
    whose intent is ambiguous is reported instead.
    """
    block = front_matter_text(text)
    if not named_contract_macros(block):
        return None
    if find_metadata_inputs(block):
        return None
    for path in find_inputs(block):
        if not (qmd.parent / path).resolve().is_file():
            return None
    return insert_reference(text, metadata_reference_for(qmd))


def _report_missing_inputs(
    root: Path, qmd: Path, block: str, references: List[str]
) -> None:
    """Report an input the document needs but that nothing here creates.

    A document that names a contract macro is asking for the generated
    file, so an input whose name breaks the convention is a naming mistake
    rather than an artifact produced elsewhere.  Reporting is confined to
    that case, which keeps a file written by a code chunk during the render
    out of it.
    """
    if not named_contract_macros(block):
        return
    for path in find_inputs(block):
        if path in references:
            continue
        if (qmd.parent / path).resolve().is_file():
            continue
        _note(
            CASE_INPUT_MISSING,
            f"{_display(qmd, root)} inputs {path}, which does not exist and "
            f"whose name does not end in _metadata.tex, so nothing here "
            f"creates it.",
        )


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
        root, _discover_documents(root, _load_build_yml_excludes(root))
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
    policy = load_metadata_policy(root)
    claimed: Dict[Path, Path] = {}
    contested: Dict[Path, List[Path]] = {}
    outside: Dict[Path, List[Path]] = {}
    written = 0
    repaired_count = 0
    missing_reference = 0

    for qmd in qmds:
        qmd = Path(qmd).resolve()
        if not qmd.is_relative_to(root):
            # A symlinked document resolves out of the tree, and its
            # reference belongs to the tree the real file lives in.  The
            # document is skipped here rather than reported as a bad
            # reference, which is what it would otherwise look like.
            if policy.is_enabled(CASE_DOCUMENT_OUTSIDE_ROOT):
                _note(
                    CASE_DOCUMENT_OUTSIDE_ROOT,
                    f"{qmd} resolves outside the docs root, skipping.",
                )
            continue

        text = _read_text(qmd)
        block = front_matter_text(text)
        references = find_metadata_inputs(block)
        if policy.is_enabled(CASE_INPUT_MISSING):
            _report_missing_inputs(root, qmd, block, references)

        if (
            not references
            and named_contract_macros(block)
            and policy.may_repair(CASE_REFERENCE_MISSING)
        ):
            repaired = _repair_missing_reference(qmd, text)
            if repaired is not None:
                try:
                    qmd.write_text(repaired, encoding="utf-8")
                except OSError as exc:
                    logger.warning("Metadata: could not write %s: %s", qmd, exc)
                else:
                    text = repaired
                    block = front_matter_text(text)
                    references = find_metadata_inputs(block)
                    if references:
                        repaired_count += 1
                        _did(
                            CASE_REFERENCE_MISSING,
                            f"added \\input{{{references[0]}}} to "
                            f"{_display(qmd, root)}, whose header names "
                            f"{', '.join(named_contract_macros(block))} with "
                            f"no generated file.",
                        )

        if not references:
            used = named_contract_macros(block)
            if used and policy.is_enabled(CASE_REFERENCE_MISSING):
                missing_reference += 1
                _note(
                    CASE_REFERENCE_MISSING,
                    f"{_display(qmd, root)} names {', '.join(used)} with no "
                    f"\\input{{..._metadata.tex}} reference, so the generated "
                    f"file has no path into the document.",
                )
            continue

        front = parse_front_matter(text)
        if front is None:
            if policy.is_enabled(CASE_INVALID_FRONT_MATTER):
                _note(
                    CASE_INVALID_FRONT_MATTER,
                    f"{_display(qmd, root)} has invalid front matter, so "
                    f"{', '.join(references)} cannot be generated from it.",
                )
            continue

        merged, sources = resolve_metadata_files(front, qmd, policy)
        used = named_contract_macros(block)
        changed = False
        for source in sources:
            if supply_affiliation_declaration(source, used, policy, root):
                changed = True
        if changed:
            merged, sources = resolve_metadata_files(front, qmd, policy)
        report_affiliation_gaps(merged, used, qmd, root, policy)

        for reference in references:
            target = (qmd.parent / reference).resolve()
            if not target.is_relative_to(root):
                outside.setdefault(target, []).append(qmd)
                continue
            owner = claimed.get(target)
            if owner is not None and owner != qmd:
                contested.setdefault(target, [owner]).append(qmd)
                continue
            claimed[target] = qmd

            inputs = [qmd] + sources
            if not _is_stale(target, inputs):
                continue
            if not policy.may_repair(CASE_METADATA_FILE):
                if policy.is_enabled(CASE_METADATA_FILE):
                    _note(
                        CASE_METADATA_FILE,
                        f"{_display(target, root)} is missing or older than "
                        f"{_display(qmd, root)}, and report_only leaves it "
                        f"alone.",
                    )
                continue

            try:
                target.parent.mkdir(parents=True, exist_ok=True)
                target.write_text(render_metadata_tex(merged, qmd), encoding="utf-8")
            except OSError as exc:
                logger.warning("Metadata: could not write %s: %s", target, exc)
                continue

            written += 1
            _did(
                CASE_METADATA_FILE,
                f"wrote {_display(target, root)} for {_display(qmd, root)}",
            )

    for target, documents in outside.items():
        if policy.is_enabled(CASE_REFERENCE_OUTSIDE_ROOT):
            _note(
                CASE_REFERENCE_OUTSIDE_ROOT,
                f"{len(documents)} document(s) reference "
                f"{_display(target, root)} outside the docs root "
                f"({', '.join(_display(document, root) for document in documents)}), "
                f"so it is left alone.",
            )

    for target, owners in contested.items():
        if policy.is_enabled(CASE_SHARED_TARGET):
            _note(
                CASE_SHARED_TARGET,
                f"{len(owners)} documents reference {_display(target, root)} "
                f"({', '.join(_display(owner, root) for owner in owners)}), so "
                f"it carries the stamp of {_display(owners[0], root)}.",
                level=logging.INFO,
            )

    if written:
        logger.info("Metadata: generated %d file(s).", written)
    else:
        logger.info("Metadata: no file needs regenerating.")
    if repaired_count:
        logger.info("Metadata: repaired %d document(s).", repaired_count)
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


def _discover_documents(
    docs_root: Path, exclude_patterns: List[str]
) -> List[Path]:
    """Return the documents that can carry a metadata reference.

    Quarto renders ``.md`` alongside ``.qmd``, and sdbs treats both as
    source documents, so both are served.
    """
    found: List[Path] = []
    for pattern in ("*.qmd", "*.md"):
        for path in docs_root.rglob(pattern):
            rel = path.relative_to(docs_root).as_posix()
            if matches_exclude(rel, exclude_patterns):
                continue
            found.append(path)
    return sorted(set(found))
