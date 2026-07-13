"""Unit tests for the SDBS publish module (``sdb.publish``)."""

from __future__ import annotations

import textwrap
from pathlib import Path
from unittest.mock import patch

import pytest
import yaml

from sdb.publish import (
    PUBLISH_DIR_NAME,
    _capture_artifact_md,
    _capture_artifact_tex,
    _copy_artifact_html,
    _copy_artifact_pdf,
    _copy_source_context,
    _gen_metadata,
    _site_path,
    get_publish_dir,
    run_publish_sequence,
)


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture
def docs_root(tmp_path: Path) -> Path:
    d = tmp_path / "docs"
    d.mkdir()
    return d


@pytest.fixture
def qmd_file(docs_root: Path) -> Path:
    """A minimal .qmd with YAML frontmatter."""
    qmd = docs_root / "paper.qmd"
    qmd.write_text(textwrap.dedent("""\
        ---
        title: "Test Paper"
        author: "Test Author"
        abstract: "A test abstract."
        bibliography: refs.bib
        ---
        # Introduction
        Hello.
    """))
    return qmd


@pytest.fixture
def sample_bib(docs_root: Path) -> Path:
    bib = docs_root / "refs.bib"
    bib.write_text("@article{key,\n  title={T},\n  author={A},\n  year={2025},\n}")
    return bib


@pytest.fixture
def sample_image(docs_root: Path) -> Path:
    img = docs_root / "fig.png"
    img.write_bytes(b"PNG")
    return img


@pytest.fixture
def metadata_tex(docs_root: Path) -> Path:
    d = docs_root / "_files"
    d.mkdir()
    tex = d / "paper_metadata.tex"
    tex.write_text(r"\newcommand{\version}{1.0}")
    return tex


@pytest.fixture
def tex_file(qmd_file: Path) -> Path:
    tex = qmd_file.parent / f"{qmd_file.stem}.tex"
    tex.write_text(r"\documentclass{article}\begin{document}Hello\end{document}")
    return tex


@pytest.fixture
def mock_target_config() -> dict:
    return {
        "paper": {"qmd": "paper.qmd"},
        "index": {"qmd": "index.qmd"},
    }


# ---------------------------------------------------------------------------
# get_publish_dir
# ---------------------------------------------------------------------------


class TestGetPublishDir:
    def test_returns_docs_child(self, docs_root: Path) -> None:
        d = get_publish_dir(docs_root)
        assert d == docs_root / PUBLISH_DIR_NAME

    def test_absolute_path(self, tmp_path: Path) -> None:
        d = get_publish_dir(tmp_path)
        assert d.is_absolute()


# ---------------------------------------------------------------------------
# _site_path
# ---------------------------------------------------------------------------


class TestSitePath:
    def test_qmd_in_root(self, docs_root: Path, qmd_file: Path) -> None:
        p = _site_path(qmd_file, docs_root, "paper", "pdf")
        assert p == docs_root / "_site" / "paper.pdf"

    def test_qmd_in_subdir(self, docs_root: Path) -> None:
        sub = docs_root / "sub"
        sub.mkdir()
        qmd = sub / "paper.qmd"
        qmd.write_text("---\ntitle: X\n---\nBody")
        p = _site_path(qmd, docs_root, "paper", "pdf")
        assert p == docs_root / "_site" / "sub" / "paper.pdf"

    def test_qmd_outside_docs_returns_empty(self, tmp_path: Path) -> None:
        outside = tmp_path / "outside.qmd"
        outside.write_text("---\ntitle: X\n---\nBody")
        p = _site_path(outside, tmp_path / "docs", "paper", "pdf")
        assert p == Path()


# ---------------------------------------------------------------------------
# _copy_source_context
# ---------------------------------------------------------------------------


class TestCopySourceContext:
    def test_copies_bib_and_images(
        self, docs_root: Path, qmd_file: Path, sample_bib: Path, sample_image: Path
    ) -> None:
        bundle = docs_root / "_publish" / "paper"
        bundle.mkdir(parents=True)

        _copy_source_context(qmd_file, bundle, docs_root)

        assert (bundle / "refs.bib").exists()
        assert (bundle / "fig.png").exists()

    def test_copies_metadata_tex(
        self, docs_root: Path, qmd_file: Path, metadata_tex: Path
    ) -> None:
        bundle = docs_root / "_publish" / "paper"
        bundle.mkdir(parents=True)

        _copy_source_context(qmd_file, bundle, docs_root)

        assert (bundle / "_files" / "paper_metadata.tex").exists()

    def test_skips_missing_bib(self, docs_root: Path, qmd_file: Path) -> None:
        bundle = docs_root / "_publish" / "paper"
        bundle.mkdir(parents=True)

        _copy_source_context(qmd_file, bundle, docs_root)

        # No refs.bib existed; bundle should have no bib
        bibs = list(bundle.glob("*.bib"))
        assert len(bibs) == 0


# ---------------------------------------------------------------------------
# _capture_artifact_tex
# ---------------------------------------------------------------------------


class TestCaptureArtifactTex:
    def test_copies_tex_from_qmd_dir(
        self, docs_root: Path, qmd_file: Path, tex_file: Path
    ) -> None:
        bundle = docs_root / "_publish" / "paper"
        bundle.mkdir(parents=True)

        _capture_artifact_tex(qmd_file, bundle, docs_root)

        assert (bundle / "paper.tex").exists()
        assert (bundle / "paper.tex").read_text() == tex_file.read_text()

    def test_no_tex_does_not_fail(
        self, docs_root: Path, qmd_file: Path
    ) -> None:
        bundle = docs_root / "_publish" / "paper"
        bundle.mkdir(parents=True)

        _capture_artifact_tex(qmd_file, bundle, docs_root)

        assert not (bundle / "paper.tex").exists()

    def test_copies_files_from_staging(
        self, docs_root: Path, qmd_file: Path
    ) -> None:
        bundle = docs_root / "_publish" / "paper"
        bundle.mkdir(parents=True)
        # Create staging with _files
        staging = bundle.parent / ".staging" / "paper" / "paper_files"
        staging.mkdir(parents=True)
        (staging / "figure-pdf").mkdir()
        (staging / "figure-pdf" / "plot-1.pdf").write_bytes(b"PDF")

        _capture_artifact_tex(qmd_file, bundle, docs_root)

        target_dir = bundle / "paper_files"
        assert target_dir.exists()
        assert (target_dir / "figure-pdf" / "plot-1.pdf").exists()

    def test_cached_scope_respects_target_boundary(
        self, docs_root: Path, qmd_file: Path
    ) -> None:
        bundle = docs_root / "_publish" / "paper"
        bundle.mkdir(parents=True)
        # Create _cached/ for a DIFFERENT target with paper_files/
        wrong_target_cache = docs_root.parent / "_cached" / "wrong-target" / "somehash"
        wrong_target_cache.mkdir(parents=True)
        (wrong_target_cache / "paper_files").mkdir()
        (wrong_target_cache / "paper_files" / "wrong.pdf").write_bytes(b"WRONG")
        # Create _cached/ for the CORRECT target without paper_files/
        correct_cache = docs_root.parent / "_cached" / "paper" / "somehash"
        correct_cache.mkdir(parents=True)
        # Only a different _files dir in the correct target
        (correct_cache / "other_files").mkdir()

        _capture_artifact_tex(qmd_file, bundle, docs_root)

        target_dir = bundle / "paper_files"
        # Should NOT pick up from wrong-target
        if target_dir.exists():
            wrong = target_dir / "wrong.pdf"
            assert not wrong.exists(), f"Picked up {wrong} from wrong target cache" 


# ---------------------------------------------------------------------------
# _capture_artifact_md
# ---------------------------------------------------------------------------


class TestCaptureArtifactMd:
    def test_from_llms(self, docs_root: Path, qmd_file: Path) -> None:
        llms = docs_root / "_llms"
        llms.mkdir(parents=True)
        (llms / "paper.llms.md").write_text("# Content")

        bundle = docs_root / "_publish" / "paper"
        bundle.mkdir(parents=True)

        _capture_artifact_md(qmd_file, bundle, docs_root)

        assert (bundle / "paper.md").exists()
        assert (bundle / "paper.md").read_text() == "# Content"

    def test_from_site_subdir(self, docs_root: Path) -> None:
        sub = docs_root / "sub"
        sub.mkdir()
        qmd = sub / "paper.qmd"
        qmd.write_text("---\ntitle: X\n---\nBody")

        site = docs_root / "_site" / "sub"
        site.mkdir(parents=True)
        (site / "paper.llms.md").write_text("# From site subdir")

        bundle = docs_root / "_publish" / "paper"
        bundle.mkdir(parents=True)

        _capture_artifact_md(qmd, bundle, docs_root)

        assert (bundle / "paper.md").exists()
        assert (bundle / "paper.md").read_text() == "# From site subdir"

    def test_no_source_does_not_fail(
        self, docs_root: Path, qmd_file: Path
    ) -> None:
        bundle = docs_root / "_publish" / "paper"
        bundle.mkdir(parents=True)

        _capture_artifact_md(qmd_file, bundle, docs_root)

        assert not (bundle / "paper.md").exists()


# ---------------------------------------------------------------------------
# _copy_artifact_pdf / _copy_artifact_html
# ---------------------------------------------------------------------------


class TestCopyArtifactPdf:
    def test_from_site(self, docs_root: Path, qmd_file: Path) -> None:
        site = docs_root / "_site"
        site.mkdir()
        (site / "paper.pdf").write_bytes(b"PDF data")

        bundle = docs_root / "_publish" / "paper"
        bundle.mkdir(parents=True)

        _copy_artifact_pdf(qmd_file, bundle, docs_root)

        assert (bundle / "paper.pdf").exists()
        assert (bundle / "paper.pdf").read_bytes() == b"PDF data"

    def test_from_site_subdir(self, docs_root: Path) -> None:
        sub = docs_root / "sub"
        sub.mkdir()
        qmd = sub / "paper.qmd"
        qmd.write_text("---\ntitle: X\n---\nBody")
        site = docs_root / "_site" / "sub"
        site.mkdir(parents=True)
        (site / "paper.pdf").write_bytes(b"PDF data")

        bundle = docs_root / "_publish" / "paper"
        bundle.mkdir(parents=True)

        _copy_artifact_pdf(qmd, bundle, docs_root)

        assert (bundle / "paper.pdf").read_bytes() == b"PDF data"

    def test_from_qmd_dir(self, docs_root: Path, qmd_file: Path) -> None:
        (qmd_file.parent / "paper.pdf").write_bytes(b"Local PDF")

        bundle = docs_root / "_publish" / "paper"
        bundle.mkdir(parents=True)

        _copy_artifact_pdf(qmd_file, bundle, docs_root)

        assert (bundle / "paper.pdf").read_bytes() == b"Local PDF"

    def test_no_pdf(self, docs_root: Path, qmd_file: Path) -> None:
        bundle = docs_root / "_publish" / "paper"
        bundle.mkdir(parents=True)
        _copy_artifact_pdf(qmd_file, bundle, docs_root)
        assert not (bundle / "paper.pdf").exists()


class TestCopyArtifactHtml:
    def test_from_site_subdir(self, docs_root: Path) -> None:
        sub = docs_root / "sub"
        sub.mkdir()
        qmd = sub / "paper.qmd"
        qmd.write_text("---\ntitle: X\n---\nBody")
        site = docs_root / "_site" / "sub"
        site.mkdir(parents=True)
        (site / "paper.html").write_text("<html></html>")

        bundle = docs_root / "_publish" / "paper"
        bundle.mkdir(parents=True)

        _copy_artifact_html(qmd, bundle, docs_root)

        assert (bundle / "paper.html").read_text() == "<html></html>"

    def test_no_html(self, docs_root: Path, qmd_file: Path) -> None:
        bundle = docs_root / "_publish" / "paper"
        bundle.mkdir(parents=True)
        _copy_artifact_html(qmd_file, bundle, docs_root)
        assert not (bundle / "paper.html").exists()


# ---------------------------------------------------------------------------
# _gen_metadata
# ---------------------------------------------------------------------------


class TestGenMetadata:
    def test_extracts_title_from_frontmatter(
        self, docs_root: Path, qmd_file: Path
    ) -> None:
        bundle = docs_root / "_publish" / "paper"
        bundle.mkdir(parents=True)
        out = bundle / "metadata.yaml"

        _gen_metadata(qmd_file, out, docs_root, "paper")

        with open(out) as f:
            meta = yaml.safe_load(f)
        assert meta["title"] == "Test Paper"

    def test_extracts_author(self, docs_root: Path, qmd_file: Path) -> None:
        bundle = docs_root / "_publish" / "paper"
        bundle.mkdir(parents=True)
        out = bundle / "metadata.yaml"

        _gen_metadata(qmd_file, out, docs_root, "paper")

        with open(out) as f:
            meta = yaml.safe_load(f)
        assert meta["creators"][0]["name"] == "Test Author"

    def test_falls_back_to_target_name(
        self, docs_root: Path
    ) -> None:
        qmd = docs_root / "paper.qmd"
        qmd.write_text("No frontmatter here")

        bundle = docs_root / "_publish" / "paper"
        bundle.mkdir(parents=True)
        out = bundle / "metadata.yaml"

        _gen_metadata(qmd, out, docs_root, "paper")

        with open(out) as f:
            meta = yaml.safe_load(f)
        assert "Paper" in meta["title"]

    def test_includes_license_from_config(
        self, docs_root: Path, qmd_file: Path
    ) -> None:
        bundle = docs_root / "_publish" / "paper"
        bundle.mkdir(parents=True)
        out = bundle / "metadata.yaml"

        # _gen_metadata reads EXTERNAL_CONFIG from sdb.build
        import sdb.build as build_mod
        build_mod.EXTERNAL_CONFIG.clear()
        build_mod.EXTERNAL_CONFIG.update({
            "publish": {
                "metadata": {
                    "license": "CC-BY-NC-4.0",
                    "keywords": ["custom"],
                }
            }
        })

        _gen_metadata(qmd_file, out, docs_root, "paper")

        with open(out) as f:
            meta = yaml.safe_load(f)
        assert meta["license"] == "CC-BY-NC-4.0"
        assert "custom" in meta["keywords"]


# ---------------------------------------------------------------------------
# run_publish_sequence
# ---------------------------------------------------------------------------


class TestRunPublishSequence:
    def test_no_targets_logs_and_returns(
        self, docs_root: Path
    ) -> None:
        with patch("sdb.build.TARGET_CONFIG", {}):
            run_publish_sequence({}, docs_root, targets=None)
            # Should not raise

    def test_skips_unknown_target(
        self, docs_root: Path
    ) -> None:
        with patch("sdb.build.TARGET_CONFIG", {}):
            run_publish_sequence(
                {}, docs_root, targets=["nonexistent"]
            )
            # Should not raise

    def test_creates_bundle_dir(
        self, docs_root: Path, qmd_file: Path
    ) -> None:
        with patch("sdb.build.TARGET_CONFIG", {"paper": {"qmd": "paper.qmd"}}):
            run_publish_sequence(
                {}, docs_root, targets=["paper"]
            )
            bundle = docs_root / "_publish" / "paper"
            assert bundle.exists()

    def test_assembles_bundle_with_artifacts(
        self, docs_root: Path, qmd_file: Path, tex_file: Path
    ) -> None:
        # Create the _site/ output that publish copies
        site = docs_root / "_site"
        site.mkdir()
        (site / "paper.pdf").write_bytes(b"PDF")
        (site / "paper.html").write_text("<html></html>")
        (site / "paper.llms.md").write_text("# MD")

        with patch("sdb.build.TARGET_CONFIG", {"paper": {"qmd": "paper.qmd"}}):
            run_publish_sequence(
                {}, docs_root, targets=["paper"]
            )

        bundle = docs_root / "_publish" / "paper"
        assert (bundle / "paper.tex").exists()
        assert (bundle / "paper.pdf").exists()
        assert (bundle / "paper.html").exists()
        assert (bundle / "paper.md").exists()
        assert (bundle / "metadata.yaml").exists()


# ---------------------------------------------------------------------------
# _capture_files_for_publish (build.py)
# ---------------------------------------------------------------------------


class TestCaptureFilesForPublish:
    def test_captures_files_to_staging(self, docs_root: Path, qmd_file: Path) -> None:
        files_dir = qmd_file.parent / "paper_files"
        files_dir.mkdir()
        (files_dir / "figure-pdf").mkdir()
        (files_dir / "figure-pdf" / "plot.pdf").write_bytes(b"PDF")
        (files_dir / "libs").mkdir()
        (files_dir / "libs" / "style.css").write_text("body {}")

        from sdb.build import _capture_files_for_publish

        # Mock TARGET_CONFIG
        with patch("sdb.build.TARGET_CONFIG", {"paper": {"qmd": "paper.qmd"}}):
            _capture_files_for_publish("paper", docs_root)

        staging = docs_root / "_publish" / ".staging" / "paper" / "paper_files"
        assert staging.exists()
        assert (staging / "figure-pdf" / "plot.pdf").exists()
        assert (staging / "libs" / "style.css").exists()

    def test_skips_when_no_files_dir(self, docs_root: Path) -> None:
        from sdb.build import _capture_files_for_publish

        with patch("sdb.build.TARGET_CONFIG", {"paper": {"qmd": "paper.qmd"}}):
            _capture_files_for_publish("paper", docs_root)
            # Should not raise

    def test_caches_alongside_artifact(
        self, docs_root: Path, qmd_file: Path
    ) -> None:
        files_dir = qmd_file.parent / "paper_files"
        files_dir.mkdir()
        (files_dir / "fig.pdf").write_bytes(b"FIG")

        from sdb.build import _capture_files_for_publish, HashManager

        qmd_hash = HashManager.compute_quarto_file_hash_with_deps(qmd_file, docs_root)
        # Pre-create the cache directory (simulates prior update_format_cache call)
        cache_dir = docs_root.parent / "_cached" / "paper" / qmd_hash
        cache_dir.mkdir(parents=True)
        expected_cache = cache_dir / "paper_files"

        with patch("sdb.build.TARGET_CONFIG", {"paper": {"qmd": "paper.qmd"}}):
            _capture_files_for_publish("paper", docs_root)

        assert expected_cache.exists()
        assert (expected_cache / "fig.pdf").exists()


# ---------------------------------------------------------------------------
# CLI integration: --publish flag forwarded to build_targets
# ---------------------------------------------------------------------------


class TestBuildCliPublishFlag:
    """Verify CLI --publish flag reach build_targets kwargs."""

    def _run(self, argv):
        from sdb.cli import main
        try:
            main(["build", *argv])
        except SystemExit:
            pass

    def test_publish_flag_false_by_default(self) -> None:
        with (
            patch("sdb.cli.build_module.build_targets") as mock_build,
            patch("sdb.cli.build_module.initialize_config"),
            patch("sdb.cli.build_module.BUILD_FUNCTIONS", {"doc": lambda: True}),
        ):
            self._run(["."])
            kw = mock_build.call_args.kwargs
            assert kw["publish"] is False

    def test_publish_flag_true_when_passed(self) -> None:
        with (
            patch("sdb.cli.build_module.build_targets") as mock_build,
            patch("sdb.cli.build_module.initialize_config"),
            patch("sdb.cli.build_module.BUILD_FUNCTIONS", {"doc": lambda: True}),
        ):
            self._run([".", "--publish"])
            kw = mock_build.call_args.kwargs
            assert kw["publish"] is True

    def test_publish_flag_only(self) -> None:
        with (
            patch("sdb.cli.build_module.build_targets") as mock_build,
            patch("sdb.cli.build_module.initialize_config"),
            patch("sdb.cli.build_module.BUILD_FUNCTIONS", {"doc": lambda: True}),
        ):
            self._run([".", "--publish"])
            kw = mock_build.call_args.kwargs
            assert kw["publish"] is True
            


class TestCliPublishCleanup:
    """_publish/ is cleaned before initialize_config to avoid target discovery."""

    def test_clean_publish_before_init(self) -> None:
        with (
            patch("sdb.cli.build_module.initialize_config"),
            patch("sdb.cli.build_module.build_targets"),
            patch("sdb.cli.build_module.BUILD_FUNCTIONS", {"doc": lambda: True}),
            patch("shutil.rmtree") as mock_rmtree,
        ):
            from tempfile import mkdtemp
            tmp = Path(mkdtemp())
            pub = tmp / "_publish"
            pub.mkdir(parents=True)
            (pub / "stale.md").write_text("stale")
            (pub / "_include").mkdir()
            (pub / "_include" / "bad.qmd").write_text("---\ntitle: bad\n---\n")

            from sdb.cli import main as cli_main
            try:
                cli_main(["build", str(tmp), "--publish"])
            except SystemExit:
                pass

            # rmtree should have been called on _publish dir
            found = False
            for call_args in mock_rmtree.call_args_list:
                if "_publish" in str(call_args):
                    found = True
                    break
            assert found, "_publish/ was not cleaned before initialize_config"

    def test_no_clean_without_publish_flag(self) -> None:
        with (
            patch("sdb.cli.build_module.initialize_config"),
            patch("sdb.cli.build_module.build_targets"),
            patch("sdb.cli.build_module.BUILD_FUNCTIONS", {"doc": lambda: True}),
            patch("shutil.rmtree") as mock_rmtree,
        ):
            from tempfile import mkdtemp
            tmp = Path(mkdtemp())
            pub = tmp / "_publish"
            pub.mkdir(parents=True)
            (pub / "stale.md").write_text("stale")

            from sdb.cli import main as cli_main
            try:
                cli_main(["build", str(tmp)])
            except SystemExit:
                pass

            # rmtree should NOT have been called on _publish
            for call_args in mock_rmtree.call_args_list:
                if "_publish" in str(call_args):
                    pytest.fail("_publish was cleaned even without --publish flag")
