"""Tests for where the build reads and writes outside the documents themselves.

``sdb build --website -j N`` copies the docs root per target and renders from
the copy.  The copy excludes ``_files/``, because that is generated output, so
the metadata file a title page inputs has to be written again inside it.

The build cache lives in the directory the command was run from, so one
directory serves either layout of the docs root.
"""

from __future__ import annotations

import logging
import shutil

import pytest
from pathlib import Path

import sdb.build as build
from sdb.build import prepare_isolated_docs

AUTHOR_YML = """author:
  - name: Example Author
    email: lee@example.org
    affiliations:
      - name: Example Foundation
        domain: example.org
        url: https://example.org
"""


def _write(path: Path, content: str) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(content, encoding="utf-8")
    return path


def _document(reference: str | None = "./_files/doc_metadata.tex") -> str:
    lines = [
        "---",
        'title: "Test"',
        "version-prefix: test_doc",
        "metadata-files:",
        "  - ./_include/author.yml",
        "format:",
        "  pdf:",
        "    include-in-header:",
        "      text: |",
    ]
    if reference is not None:
        lines.append(f"        \\input{{{reference}}}")
    lines += [
        "        {\\large \\affiliationname \\par}",
        "---",
        "",
        "Body.",
        "",
    ]
    return "\n".join(lines)


def _copied_tree(tmp_path: Path, document: str) -> Path:
    """The tree a website build renders from, with no generated directory."""
    _write(tmp_path / "_include" / "author.yml", AUTHOR_YML)
    _write(tmp_path / "build.yml", 'exclude:\n  - "**/*_files/"\n')
    _write(tmp_path / "doc.qmd", document)
    return tmp_path


class TestPrepareIsolatedDocs:
    """prepare_isolated_docs() serves a target inside its own copy."""

    def test_writes_the_metadata_file_the_header_inputs(self, tmp_path: Path) -> None:
        _copied_tree(tmp_path, _document())
        prepare_isolated_docs(tmp_path, "doc.qmd")
        written = (tmp_path / "_files" / "doc_metadata.tex").read_text(
            encoding="utf-8"
        )
        assert "\\newcommand{\\affiliationname}{Example Foundation}" in written

    def test_repairs_a_header_that_names_a_macro_without_a_reference(
        self, tmp_path: Path
    ) -> None:
        """The incident state reaches the copy too, so the reference the
        header needs is inserted there rather than only in the original."""
        _copied_tree(tmp_path, _document(reference=None))
        prepare_isolated_docs(tmp_path, "doc.qmd")
        assert "\\input{./_files/doc_metadata.tex}" in (
            tmp_path / "doc.qmd"
        ).read_text(encoding="utf-8")
        assert (tmp_path / "_files" / "doc_metadata.tex").is_file()

    def test_a_document_that_asks_for_nothing_creates_nothing(
        self, tmp_path: Path
    ) -> None:
        _copied_tree(tmp_path, "---\ntitle: T\n---\n\nBody.\n")
        prepare_isolated_docs(tmp_path, "doc.qmd")
        assert not (tmp_path / "_files").exists()

    def test_a_target_without_a_document_is_a_no_op(self, tmp_path: Path) -> None:
        _copied_tree(tmp_path, _document())
        prepare_isolated_docs(tmp_path, None)
        prepare_isolated_docs(tmp_path, "")
        assert not (tmp_path / "_files").exists()

    def test_a_document_absent_from_the_copy_is_a_no_op(self, tmp_path: Path) -> None:
        _copied_tree(tmp_path, _document())
        prepare_isolated_docs(tmp_path, "elsewhere/doc.qmd")
        assert not (tmp_path / "_files").exists()

    def test_a_failure_is_reported_rather_than_raised(
        self, tmp_path: Path, caplog, monkeypatch
    ) -> None:
        """A metadata failure must not take the copy down, which would abort
        the whole build; the render reports the missing file instead."""
        _copied_tree(tmp_path, _document())

        def _boom(*args, **kwargs):
            raise RuntimeError("boom")

        monkeypatch.setattr("sdb.build.generate_metadata_for", _boom)
        with caplog.at_level(logging.WARNING):
            prepare_isolated_docs(tmp_path, "doc.qmd")
        assert any(
            "Metadata generation failed" in str(record.message)
            for record in caplog.records
        )


class TestCacheLocation:
    """The build cache lives where the command was run.

    One directory serves a layout whose documents sit in a subdirectory and one
    whose docs root is the repository root, so a caller caches the same place in
    either case, and nothing the build writes sits outside the tree the caller
    checked out.
    """

    def test_the_invocation_directory_is_the_cache_parent(
        self, tmp_path: Path, monkeypatch
    ) -> None:
        monkeypatch.setattr(build, "CACHE_ROOT", tmp_path)
        assert build.cache_parent(tmp_path / "docs") == tmp_path

    def test_the_layout_does_not_move_the_cache(
        self, tmp_path: Path, monkeypatch
    ) -> None:
        monkeypatch.setattr(build, "CACHE_ROOT", tmp_path)
        assert build.get_cache_base(tmp_path / "docs") == tmp_path / ".sdbtmp_cache"
        assert build.get_cache_base(tmp_path) == tmp_path / ".sdbtmp_cache"

    def test_an_uninitialized_caller_stays_inside_the_tree_it_named(
        self, tmp_path: Path, monkeypatch
    ) -> None:
        monkeypatch.setattr(build, "CACHE_ROOT", None)
        elsewhere = tmp_path / "elsewhere"
        elsewhere.mkdir()
        monkeypatch.chdir(elsewhere)

        assert build.get_cache_base(tmp_path / "docs") == tmp_path / "docs" / ".sdbtmp_cache"

    def test_initialize_config_reads_the_invocation_directory(
        self, tmp_path: Path, monkeypatch
    ) -> None:
        """The policy is read once, from where the command was run."""
        monkeypatch.chdir(tmp_path)
        (tmp_path / "docs").mkdir()
        # initialize_config writes state that outlives the test.
        for name in (
            "CACHE_ROOT",
            "JUPYTER_CACHE_PATH",
            "EXTERNAL_CONFIG",
            "TARGET_CONFIG",
            "BUILD_FUNCTIONS",
            "OUTPUT_DIR_TARGETS",
        ):
            monkeypatch.setattr(build, name, getattr(build, name))
        monkeypatch.setenv("JUPYTERCACHE", "")

        build.initialize_config(tmp_path / "docs")

        assert build.CACHE_ROOT == tmp_path
        assert build.get_cache_base(tmp_path) == tmp_path / ".sdbtmp_cache"
        assert (tmp_path / ".sdbtmp_jupyter").is_dir()


class TestCacheDirectoriesAreNamed:
    """One marker names every folder the build writes for itself, so a rule
    covers a folder this engine has not grown yet as well as the ones it has."""

    def test_the_hash_pair_lives_under_the_target_in_the_cache(
        self, tmp_path: Path, monkeypatch
    ) -> None:
        """A document is keyed by its target name and not by its file name.

        Two ``index.qmd`` in different directories are two targets, so their
        records cannot collide.  That is what the path this replaces reached for
        the parent folder's name to avoid.
        """
        monkeypatch.setattr(build, "CACHE_ROOT", tmp_path)
        root_index = build.get_cache_file("index", "html", tmp_path / "docs")
        sub_index = build.get_cache_file("rem-index", "html", tmp_path / "docs")

        assert root_index == tmp_path / ".sdbtmp_cache" / "index" / "rendered_html.txt"
        assert sub_index == tmp_path / ".sdbtmp_cache" / "rem-index" / "rendered_html.txt"

    def test_the_cache_base_holds_only_target_directories(
        self, tmp_path: Path, monkeypatch
    ) -> None:
        """What the build records for a target belongs inside that target.

        The set of cached targets is read from the top level of the cache base, so
        a record that landed there would be read as a target of its own and would
        keep the sidebar re-render decision always awake.
        """
        monkeypatch.setattr(build, "CACHE_ROOT", tmp_path)
        for target in ("index", "rem-index"):
            for fmt in ("html", "pdf"):
                marker = build.get_cache_file(target, fmt, tmp_path / "docs")
                build.write_hash_pair(marker, "a" * 64, "b" * 64)

        cache_base = build.get_cache_base(tmp_path / "docs")
        directories = {entry.name for entry in cache_base.iterdir() if entry.is_dir()}

        assert directories == {"index", "rem-index"}

    def test_the_marker_names_every_folder_the_build_writes(self) -> None:
        """Every name the engine derives carries the one marker, bar the copy.

        The copy a parallel website build renders from is the parent directory of
        the document Quarto is given, so its name is also a render input.  Quarto
        resolves a project through that path and a hidden component stops the
        search, so this one folder is spelled with the plain underscore and the
        engine keeps a second pattern for it.
        """
        from sdb.config import (
            BUILD_CACHE_DIR,
            BUILD_TEMP_DIR,
            DISCOVERY_EXCLUDE_PATTERNS,
            JUPYTER_CACHE_DIR,
            SDB_TEMP_PREFIX,
        )

        assert SDB_TEMP_PREFIX.startswith(".")
        assert not BUILD_TEMP_DIR.startswith(".")
        assert DISCOVERY_EXCLUDE_PATTERNS == [
            f"**/{SDB_TEMP_PREFIX}*/",
            f"**/{BUILD_TEMP_DIR}/",
        ]

        names = [BUILD_CACHE_DIR, JUPYTER_CACHE_DIR]
        for name in names:
            assert name.startswith(SDB_TEMP_PREFIX), name

    def test_discovery_reads_no_folder_that_carries_the_marker(
        self, tmp_path: Path
    ) -> None:
        """A document the build wrote never becomes a target of the next build."""
        from sdb.config import (
            BUILD_CACHE_DIR,
            BUILD_TEMP_DIR,
            ConfigManager,
            JUPYTER_CACHE_DIR,
        )

        document = "---\ntitle: x\n---\n"
        _write(tmp_path / "index.qmd", document)
        for name in (BUILD_CACHE_DIR, JUPYTER_CACHE_DIR, BUILD_TEMP_DIR):
            (tmp_path / name).mkdir()
            _write(tmp_path / name / "written.qmd", document)
            (tmp_path / "sub" / name).mkdir(parents=True)
            _write(tmp_path / "sub" / name / "written.qmd", document)

        targets = ConfigManager.discover_quarto_targets(tmp_path)

        assert set(targets) == {"index"}

    def test_the_marker_covers_a_folder_the_engine_has_not_grown(self) -> None:
        """The skip follows the marker, rather than a list of the folders."""
        ignore = build.ignore_quarto_artifacts()
        assert ".sdbtmp_whatever" in ignore("docs", [".sdbtmp_whatever", "index.qmd"])

    def test_the_copy_skip_names_the_cache_directories(self) -> None:
        ignore = build.ignore_quarto_artifacts()
        for name in (
            ".sdbtmp_cache",
            ".sdbtmp_jupyter",
            "_sdbtmp_build",
            "_site",
        ):
            assert name in ignore("docs", [name, "index.qmd"]), name

    def test_the_copy_leaves_the_cache_behind(self, tmp_path: Path) -> None:
        """The copy a target renders from carries no cache, and no scratch space.

        The skip follows the marker rather than a list of names, and it holds at
        every level, so a tree that carries a marked folder beside a document,
        which is what an older version of this engine wrote, hands none of it to a
        copy."""
        source = tmp_path / "docs"
        names = (
            ".sdbtmp_cache",
            ".sdbtmp_jupyter",
            "_sdbtmp_build",
            ".sdbtmp_index_cache",
            "_site",
        )
        for name in names:
            (source / name / "inner").mkdir(parents=True)
            (source / "sub" / name / "inner").mkdir(parents=True)
        _write(source / "index.qmd", "---\ntitle: x\n---\n")
        destination = tmp_path / "copy"

        shutil.copytree(source, destination, ignore=build.ignore_quarto_artifacts())

        assert (destination / "index.qmd").is_file()
        for name in names:
            assert not (destination / name).exists(), name
            assert not (destination / "sub" / name).exists(), f"sub/{name}"

    def test_clean_keeps_the_caches_a_build_reuses(self, tmp_path: Path) -> None:
        """A clean leaves the caches, so the next build finds them."""
        caches = (
            ".sdbtmp_jupyter",
            ".sdbtmp_cache",
            ".quarto",
            ".rumdl_cache",
            ".jupyter_cache",
        )
        for name in caches:
            (tmp_path / name / "inner").mkdir(parents=True)
        (tmp_path / "_sdbtmp_build" / "index").mkdir(parents=True)
        (tmp_path / "_site").mkdir()
        (tmp_path / "index.pdf").write_text("%PDF")

        assert build.clean_quarto_artifacts(tmp_path) is True

        for name in caches:
            assert (tmp_path / name).exists(), name
        assert not (tmp_path / "_sdbtmp_build").exists()
        assert not (tmp_path / "_site").exists()
        assert not (tmp_path / "index.pdf").exists()

    def test_clean_all_removes_the_caches_too(self, tmp_path: Path) -> None:
        """The 'all' layer takes everything a build wrote, its caches included."""
        names = (
            ".sdbtmp_jupyter",
            ".sdbtmp_cache",
            ".quarto",
            ".rumdl_cache",
            ".jupyter_cache",
            "_sdbtmp_build",
            "_site",
        )
        for name in names:
            (tmp_path / name / "inner").mkdir(parents=True)

        assert build.clean_quarto_artifacts(tmp_path, caches=True) is True

        for name in names:
            assert not (tmp_path / name).exists(), name

    def test_clean_reaches_what_a_build_wrote_beside_a_docs_root(
        self, tmp_path: Path
    ) -> None:
        """A docs root in a subdirectory keeps its scratch and its cache at the parent.

        The build writes where the command was run, so a project whose documents
        sit in ``docs/`` has its caches one level above the directory ``clean`` is
        given.  The scratch space goes in both layers and the caches only in the
        one that asks for them, which is what keeps the tree clean in that layout.
        """
        docs = tmp_path / "docs"
        docs.mkdir()
        for name in (".sdbtmp_cache", ".sdbtmp_jupyter", "_sdbtmp_build", ".rumdl_cache"):
            (tmp_path / name / "index").mkdir(parents=True)

        assert build.clean_quarto_artifacts(docs) is True

        assert not (tmp_path / "_sdbtmp_build").exists()
        assert (tmp_path / ".sdbtmp_cache").exists()
        assert (tmp_path / ".sdbtmp_jupyter").exists()
        assert (tmp_path / ".rumdl_cache").exists()

        assert build.clean_quarto_artifacts(docs, caches=True) is True

        assert not (tmp_path / ".sdbtmp_cache").exists()
        assert not (tmp_path / ".sdbtmp_jupyter").exists()
        assert not (tmp_path / ".rumdl_cache").exists()

    def test_the_layers_differ_only_by_the_caches(self) -> None:
        """Every artifact pattern is in both layers, and the caches only in 'all'."""
        manager = build.CleanupManager()
        artifacts = manager.patterns()
        everything = manager.patterns(caches=True)

        assert set(artifacts) < set(everything)
        assert set(everything) - set(artifacts) == set(
            manager.CACHE_PATTERNS + manager.OUTSIDE_CACHE_PATTERNS
        )


class TestCacheWritesAreAtomic:
    """One cache serves every render, so a reader must not see a partial file."""

    def _destination(self, tmp_path: Path) -> Path:
        destination = tmp_path / "cache" / "x.html"
        destination.parent.mkdir(parents=True)
        destination.write_text("old", encoding="utf-8")
        return destination

    def test_a_copy_replaces_the_destination(self, tmp_path: Path) -> None:
        source = _write(tmp_path / "rendered.html", "new")
        destination = self._destination(tmp_path)

        build._atomic_copy(source, destination)

        assert destination.read_text(encoding="utf-8") == "new"
        assert list(destination.parent.iterdir()) == [destination]

    def test_a_failed_copy_leaves_the_destination_alone(
        self, tmp_path: Path, monkeypatch
    ) -> None:
        source = _write(tmp_path / "rendered.html", "new")
        destination = self._destination(tmp_path)

        def refuse(source_name, destination_name):
            raise OSError("no space left on device")

        monkeypatch.setattr("sdb.build.shutil.copy2", refuse)

        with pytest.raises(OSError):
            build._atomic_copy(source, destination)

        assert destination.read_text(encoding="utf-8") == "old"
        assert list(destination.parent.iterdir()) == [destination]


class TestCacheActivityIsReported:
    """A build states what the cache did, so a caller reads a line, not the log."""

    def test_the_summary_states_the_counts_and_the_root(
        self, tmp_path: Path, monkeypatch
    ) -> None:
        monkeypatch.setattr(build, "CACHE_ROOT", tmp_path)
        build.reset_cache_activity()
        build.note_cache_activity("artifacts")
        build.note_cache_activity("served")
        build.note_cache_activity("served")

        assert build.cache_activity_summary(tmp_path) == (
            "Cache: 1 artifact(s) written, "
            "2 target(s) served entirely from the cache, "
            f"root {tmp_path / '.sdbtmp_cache'}"
        )

    def test_a_reset_clears_the_counts(self, tmp_path: Path, monkeypatch) -> None:
        monkeypatch.setattr(build, "CACHE_ROOT", tmp_path)
        build.note_cache_activity("artifacts")
        build.reset_cache_activity()

        assert "Cache: 0 artifact(s) written" in build.cache_activity_summary(tmp_path)
