"""The title-meta include has to find the document it is rendered for.

Quarto gives a cell three variables and no single one of them holds the
document.  ``QUARTO_DOCUMENT_PATH`` is the document directory relative to the
project, ``QUARTO_PROJECT_DIR`` is the directory the render treats as the
project, and the directory a cell executes in is the document's own when the
render is given a single file, which is how a parallel website build renders.
Measured on Quarto 1.9.31: a document at ``sub/doc.qmd`` reported
``QUARTO_DOCUMENT_PATH=sub`` with ``QUARTO_PROJECT_DIR`` and the working
directory both at ``<project>/sub``, so the join of the first two landed on
``sub/sub/doc.qmd`` and the render failed with FileNotFoundError.

These tests run the template include's first block the way a render does, and
assert it resolves the document from a subdirectory and from the root.
"""

from __future__ import annotations

import os
import re
from pathlib import Path

import pytest

TEMPLATE = (
    Path(__file__).resolve().parents[1]
    / "src"
    / "sdb"
    / "templates"
    / "advanced"
    / "_include"
    / "_title_meta_items.qmd"
)

DOCUMENT = "---\ntitle: probe\n---\n"


def _project(tmp_path: Path) -> Path:
    project = tmp_path / "project"
    (project / "sub").mkdir(parents=True)
    (project / "_quarto.yml").write_text("project:\n  type: website\n", encoding="utf-8")
    (project / "index.qmd").write_text(DOCUMENT, encoding="utf-8")
    (project / "sub" / "doc.qmd").write_text(DOCUMENT, encoding="utf-8")
    return project


def _run_include_block(monkeypatch: pytest.MonkeyPatch, directory: Path) -> dict:
    text = TEMPLATE.read_text(encoding="utf-8")
    block = re.findall(r"```\{python\}(.*?)```", text, re.S)[0]
    monkeypatch.chdir(directory)
    namespace: dict = {"__name__": "__main__"}
    exec(compile(block, str(TEMPLATE), "exec"), namespace)
    return namespace


def _environment(monkeypatch: pytest.MonkeyPatch, **values: str) -> None:
    for name, value in values.items():
        monkeypatch.setenv(name, value)


class TestTheIncludeLocatesItsDocument:
    def test_a_document_in_a_subdirectory(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        project = _project(tmp_path)
        document_dir = project / "sub"
        _environment(
            monkeypatch,
            QUARTO_PROJECT_DIR=str(document_dir),
            QUARTO_DOCUMENT_PATH="sub",
            QUARTO_DOCUMENT_FILE="doc.qmd",
        )

        namespace = _run_include_block(monkeypatch, document_dir)

        assert namespace["qmd_path"] == document_dir / "doc.qmd"

    def test_a_document_at_the_project_root(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        project = _project(tmp_path)
        _environment(
            monkeypatch,
            QUARTO_PROJECT_DIR=str(project),
            QUARTO_DOCUMENT_PATH=".",
            QUARTO_DOCUMENT_FILE="index.qmd",
        )

        namespace = _run_include_block(monkeypatch, project)

        assert namespace["qmd_path"] == project / "index.qmd"

    def test_a_render_that_runs_a_cell_in_the_project_directory(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """A project render executes in the project, and the join must follow."""
        project = _project(tmp_path)
        _environment(
            monkeypatch,
            QUARTO_PROJECT_DIR=str(project),
            QUARTO_DOCUMENT_PATH="sub",
            QUARTO_DOCUMENT_FILE="doc.qmd",
        )

        namespace = _run_include_block(monkeypatch, project)

        assert namespace["qmd_path"] == project / "sub" / "doc.qmd"

    def test_the_title_meta_items_are_built_for_the_document(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        project = _project(tmp_path)
        document_dir = project / "sub"
        _environment(
            monkeypatch,
            QUARTO_PROJECT_DIR=str(document_dir),
            QUARTO_DOCUMENT_PATH="sub",
            QUARTO_DOCUMENT_FILE="doc.qmd",
        )

        namespace = _run_include_block(monkeypatch, document_dir)

        assert set(namespace["title_meta_items"]) == {"html", "pdf"}
        assert os.environ["QUARTO_DOCUMENT_FILE"] == "doc.qmd"
