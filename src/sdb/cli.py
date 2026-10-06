"""
SDBS CLI — entry point for all sdb commands.

Subcommands:
  init     Scaffold a new docs directory with default templates.
  build    Build one or more Quarto targets, as a website or as an article.
  check    Validate links, citations, and cross-references.
  pre      Run pre-render steps (latest docs, path resolution, formatting).
  render   Locate .qmd files by short name and render them directly (no preprocessing).
  deploy   Run the external deploy plugins a project activates.
  plugins  List the deploy plugins found on the plugin path.
  clean    Remove Quarto build artifacts.

Every command that operates on a project takes the directory as its first
positional argument: init takes the directory to scaffold, build, check, pre,
render, and clean take the docs root the documents live in, and deploy and
plugins take the directory holding ``_deploy.yml``.
"""

import argparse
import logging
import os
import sys
from pathlib import Path

from sdb import __version__

from . import build as build_module
from . import deploy as deploy_module
from . import init as init_module


logging.basicConfig(
    level=logging.INFO,
    format="%(message)s",
    stream=sys.stderr,
)


def _add_global_args(parser: argparse.ArgumentParser) -> None:
    parser.add_argument(
        "--version",
        action="version",
        version=f"%(prog)s {__version__}",
    )


def _build_article(
    docs_root: Path, targets: list[str], output_dir: Path | None
) -> bool:
    """Render the article form of the selected targets and assemble their artifacts.

    The article goes through the renderer rather than through the site
    orchestration: it is a document's publication artifact rather than a page, so
    it neither reads nor writes the site directory the deploy channel publishes.
    The built-in pre-build sequence runs first, since it edits the text the
    version stamp covers, and a stamp that covers pre-edited bytes would disagree
    with the one a full build writes for the same document.
    """
    from .utils.quick_render import article_artifacts, render_qmd

    documents: list[Path] = []
    for target in targets:
        qmd = (build_module.TARGET_CONFIG.get(target) or {}).get("qmd")
        if not qmd:
            logger.error(
                "sdb build --article: %s has no document to render", target
            )
            return False
        documents.append(docs_root / qmd)
    if not documents:
        logger.error("sdb build --article: no target to render")
        return False
    documents = list(dict.fromkeys(documents))

    build_module.run_pre_build_sequence(
        build_module.EXTERNAL_CONFIG, docs_root, targets
    )

    success = True
    for document in documents:
        if not render_qmd(document, cwd=docs_root, format="pdf"):
            success = False
    if not success:
        return False

    total = article_artifacts(documents, output_dir)
    logging.info(
        "Assembled %d artifact(s) for %d document(s).", total, len(documents)
    )
    return True


def _setup_logging() -> None:
    """Configure proper logging with timestamps when running commands."""
    root = logging.getLogger()
    if not root.handlers:
        handler = logging.StreamHandler(sys.stderr)
        handler.setFormatter(
            logging.Formatter("%(asctime)s - %(levelname)s - %(message)s",
                              datefmt="%Y-%m-%d %H:%M:%S")
        )
        root.addHandler(handler)
        root.setLevel(logging.INFO)


def _require_docs_root(docs_root: Path, command: str) -> None:
    """Stop when the named docs root is not a directory.

    Every project-scoped command takes the docs root from the command line, so a
    typo or a wrong working directory would otherwise walk no documents, report
    success, and leave the failure to surface later as an unreadable render error.
    """
    if docs_root.is_dir():
        return
    print(
        f"sdb {command}: docs root is not a directory: {docs_root}\n"
        f"  Pass the directory the project is rooted at.",
        file=sys.stderr,
    )
    sys.exit(1)


def main(argv: list[str] | None = None) -> None:
    parser = argparse.ArgumentParser(
        prog="sdb",
        description="SSCCS Documentation Build System (SDBS)",
    )
    _add_global_args(parser)

    subparsers = parser.add_subparsers(dest="command", required=True)

    # --- init ---
    init_parser = subparsers.add_parser(
        "init",
        help="Scaffold a docs directory with default templates",
        description="Create a complete docs directory skeleton with Quarto project config, "
        "format options, citation style, and a starter landing page.",
    )
    init_parser.add_argument(
        "path",
        type=Path,
        nargs="?",
        default=Path("docs"),
        help="Target directory (default: docs/)",
    )
    init_parser.add_argument(
        "--force",
        action="store_true",
        help="Overwrite existing files",
    )
    init_parser.add_argument(
        "--template",
        type=str,
        default=None,
        help="Template flavour (omit to see available choices)",
    )

    # --- build ---
    build_parser = subparsers.add_parser(
        "build",
        help="Build Quarto document targets",
        description="Orchestrate Quarto rendering for one or more document targets. "
        "Supports parallel execution, a website output, and an article output. "
        "With neither --website nor --article, each target renders the formats "
        "its own configuration declares.\n\n"
        "--website renders the website profile. --article renders the PDF form of "
        "each target and assembles the distribution an article is published as "
        "(the PDF, its LaTeX source, the figures, and the media), which is the "
        "form an external deploy channel carries. The two are mutually exclusive.",
        epilog=(
            "Examples:\n"
            "  sdb build docs whitepaper\n"
            "  sdb build docs whitepaper proposal --website -j 4\n"
            "  sdb build docs --article\n"
            "  sdb build docs snapshot\n"
            "  sdb clean docs"
        ),
    )
    build_parser.add_argument(
        "docs_root",
        type=Path,
        nargs="?",
        default=Path("."),
        help="Path to the docs directory (default: current directory)",
    )
    build_parser.add_argument(
        "targets",
        nargs="*",
        default=["all"],
        help="Build targets: any discovered .qmd/.md file, 'all' (default), "
        "'snapshot' to refresh cache",
    )
    build_parser.add_argument(
        "--output-dir", "-o", type=Path, default=None,
        help="Directory to place final outputs",
    )
    build_output = build_parser.add_mutually_exclusive_group()
    build_output.add_argument(
        "--website", action="store_true",
        help="Use Quarto website profile (isolated parallel rendering)",
    )
    build_output.add_argument(
        "--article", action="store_true",
        help="Render each target as an article and assemble its distribution",
    )
    build_parser.add_argument(
        "--sequence", "-s", action="store_true",
        help="Force sequential execution",
    )
    build_parser.add_argument(
        "--jobs", "-j", type=int, default=None,
        help="Max parallel jobs (default: physical core count)",
    )
    build_parser.add_argument(
        "--parallel-formats", action="store_true",
        help="Render each format in separate Quarto commands",
    )
    build_parser.add_argument(
        "--config", "-c", type=Path, default=None,
        help="Path to external YAML configuration file (default: build.yml in docs root)",
    )

    # --- check ---
    check_parser = subparsers.add_parser(
        "check",
        help="Validate documentation integrity",
        description="Check links, citations, cross-references, and YAML paths "
        "in a docs directory.",
    )
    check_parser.add_argument(
        "docs_root",
        type=Path,
        nargs="?",
        default=Path("."),
        help="Path to the docs directory (default: current directory)",
    )
    check_parser.add_argument(
        "--validate-only", action="store_true",
        help="Report issues without modifying files",
    )
    check_parser.add_argument(
        "--cleanup-uncited", action="store_true",
        help="Remove uncited bibliography entries",
    )

    # --- pre ---
    pre_parser = subparsers.add_parser(
        "pre",
        help="Run pre-render steps (latest docs, path resolution, formatting)",
        description="Execute the default pre-build sequence: generate latest docs, "
        "resolve relative paths and includes, dedupe footnote references, "
        "and format QMD/MD files. "
        "These same steps run automatically before every build.",
    )
    pre_parser.add_argument(
        "docs_root",
        type=Path,
        nargs="?",
        default=Path("."),
        help="Path to the docs directory (default: current directory)",
    )

    # --- render (quick render by short name) ---
    render_parser = subparsers.add_parser(
        "render",
        help="Locate .qmd files by short name and render them directly",
        description="Search the docs root for .qmd files whose stem "
        "matches one or more short names (e.g. 'map' → "
        "docs/projects/section/chapter/map/index.qmd) and render them by calling the "
        "underlying tool directly, without the full SDBS preprocessing pipeline "
        "(include resolution, footnote cleanup, formatting, and the latest-docs "
        "list are skipped).  The metadata file a PDF or beamer header consumes is "
        "a build input rather than preprocessing, so the step that writes it runs "
        "here as well: it writes the file for the selected documents when it is "
        "missing or stale, inserts the reference a header that names a metadata "
        "macro needs, and supplies the affiliation keys a header links with.\n\n"
        "Multiple patterns can be given to render several documents in sequence "
        "(e.g. 'sdb render docs map id').  Contrast this with 'sdb build', which "
        "runs the full SDBS pipeline before rendering.  Use 'render' when you only "
        "need a quick preview or to verify the document structure.\n\n"
        "When multiple files match, prompts for selection unless --all is given.",
        epilog=(
            "Examples:\n"
            "  sdb render docs map\n"
            "  sdb render docs map --to pdf\n"
            "  sdb render docs chapter/map\n"
            "  sdb render docs map id wp"
        ),
    )
    render_parser.add_argument(
        "docs_root",
        type=Path,
        help="Path to the docs directory to search",
    )
    render_parser.add_argument(
        "patterns",
        type=str,
        nargs="+",
        help="One or more short names or path fragments to match against .qmd "
        "file stems (e.g. 'map', 'whitepaper', 'chapter/map')",
    )
    render_parser.add_argument(
        "--to", "-t", dest="format", type=str, default=None,
        help="Output format passed to quarto render --to (e.g. html, pdf)",
    )
    render_parser.add_argument(
        "--all", "-a", action="store_true",
        help="Render all matching files without prompting",
    )

    # --- deploy (external plugins) ---
    deploy_parser = subparsers.add_parser(
        "deploy",
        help="Run the external deploy plugins a project activates",
        description="Read '_deploy.yml' in the project root and run each plugin it "
        "names. A plugin is an external tool with a manifest.yml at its root, found "
        "on the plugin path (SDB_PLUGIN_PATH, then <root>/plugins). A plugin that is "
        "named but not found is skipped unless the activation sets require: true, "
        "and an option the manifest does not declare fails the run. "
        "sdbs carries no plugin code.\n\n"
        "The endpoint, region, and credentials come from the environment, so deploy "
        "runs as its own step from the render, which executes project code.",
        epilog=(
            "Examples:\n"
            "  sdb deploy docs\n"
            "  sdb deploy . --dry-run\n"
            "  sdb deploy . --require-all\n"
        ),
    )
    deploy_parser.add_argument(
        "docs_root",
        type=Path,
        nargs="?",
        default=Path("."),
        help="Directory holding _deploy.yml (default: current directory)",
    )
    deploy_parser.add_argument(
        "--config", "-c", type=Path, default=None,
        help="Path to the deploy configuration (default: <docs_root>/_deploy.yml)",
    )
    deploy_parser.add_argument(
        "--plugin-path", action="append", default=None,
        help="Extra directory to search for plugin manifests (repeatable)",
    )
    deploy_parser.add_argument(
        "--dry-run", action="store_true",
        help="Ask each plugin to report without contacting its store",
    )
    deploy_parser.add_argument(
        "--require-all", action="store_true",
        help="Fail when an activated plugin is not found",
    )
    deploy_parser.add_argument(
        "--timeout", type=float, default=deploy_module.DEFAULT_TIMEOUT,
        metavar="SECONDS",
        help="Seconds to allow each plugin before failing "
        f"(default: {deploy_module.DEFAULT_TIMEOUT:g})",
    )

    # --- plugins (introspect the plugin path) ---
    plugins_parser = subparsers.add_parser(
        "plugins",
        help="List the deploy plugins found on the plugin path",
        description="Scan the plugin path (SDB_PLUGIN_PATH, then <docs_root>/plugins) "
        "and list each plugin manifest: its name, its path, and its description.",
    )
    plugins_parser.add_argument(
        "docs_root",
        type=Path,
        nargs="?",
        default=Path("."),
        help="Directory whose plugins directory is searched (default: current directory)",
    )
    plugins_parser.add_argument(
        "--plugin-path", action="append", default=None,
        help="Extra directory to search for plugin manifests (repeatable)",
    )

    # --- clean ---
    clean_parser = subparsers.add_parser(
        "clean",
        help="Remove Quarto build artifacts",
        description="Delete all Quarto rendering artifacts (_cached/, _files/, html, pdf, tex) "
        "from the docs directory. Run before committing to avoid bloat.",
    )
    clean_parser.add_argument(
        "docs_root",
        type=Path,
        nargs="?",
        default=Path("."),
        help="Path to the docs directory (default: current directory)",
    )

    args = parser.parse_args(argv)

    if args.command == "init":
        template = args.template
        if template is None:
            templates_dir = init_module.TEMPLATES_PACKAGE
            available = sorted(
                [d.name for d in templates_dir.iterdir() if d.is_dir()]
            )
            print("Available templates:")
            for i, name in enumerate(available, 1):
                print(f"  {i}. {name}")
            while True:
                try:
                    choice = input(
                        f"Select template [1-{len(available)}] (default: 1): "
                    ).strip()
                    if not choice:
                        choice = "1"
                    idx = int(choice) - 1
                    if 0 <= idx < len(available):
                        template = available[idx]
                        break
                except (ValueError, IndexError):
                    pass
                print(
                    f"Invalid choice. Enter 1-{len(available)}.",
                    file=sys.stderr,
                )
        success = init_module.scaffold(
            args.path, force=args.force, template=template
        )
        sys.exit(0 if success else 1)

    elif args.command == "build":
        _setup_logging()
        docs_root = args.docs_root.resolve()
        _require_docs_root(docs_root, "build")

        # Load config
        config_path = args.config
        if config_path is None:
            default_config = docs_root / "build.yml"
            if default_config.exists():
                config_path = default_config

        build_module.initialize_config(docs_root, config_path)

        if args.article:
            ignored = [
                flag
                for flag, given in (
                    ("--sequence", args.sequence),
                    ("--jobs", args.jobs is not None),
                    ("--parallel-formats", args.parallel_formats),
                )
                if given
            ]
            if ignored:
                logging.error(
                    "sdb build --article: %s does not apply; an article is "
                    "rendered document by document",
                    ", ".join(ignored),
                )
                sys.exit(1)
            if "snapshot" in args.targets:
                logging.error(
                    "sdb build --article: 'snapshot' does not apply; it refreshes "
                    "the site cache an article build does not use"
                )
                sys.exit(1)
            if "all" in args.targets:
                article_targets = list(build_module.BUILD_FUNCTIONS.keys())
            else:
                article_targets = build_module.parse_targets(args.targets)
                build_module.ensure_explicit_targets(docs_root, article_targets)
                article_targets = build_module.validate_targets(article_targets)
            success = _build_article(docs_root, article_targets, args.output_dir)
            sys.exit(0 if success else 1)

        # Handle "snapshot"
        if "snapshot" in args.targets:
            snapshot_targets = [t for t in args.targets if t != "snapshot"]
            if not snapshot_targets:
                snapshot_targets = list(build_module.BUILD_FUNCTIONS.keys())
            else:
                snapshot_targets = build_module.parse_targets(snapshot_targets)
                if "all" in snapshot_targets:
                    snapshot_targets = list(build_module.BUILD_FUNCTIONS.keys())
                else:
                    build_module.ensure_explicit_targets(docs_root, snapshot_targets)
                    snapshot_targets = build_module.validate_targets(snapshot_targets)
            success = True
            for target in snapshot_targets:
                if not build_module.refresh_cache_for_target(
                    target, output_dir=args.output_dir,
                    docs_root=docs_root,
                    target_config=build_module.TARGET_CONFIG,
                ):
                    success = False
            sys.exit(0 if success else 1)

        # Handle "all"
        if "all" in args.targets:
            targets = list(build_module.BUILD_FUNCTIONS.keys())
        else:
            targets = build_module.parse_targets(args.targets)
            build_module.ensure_explicit_targets(docs_root, targets)
            targets = build_module.validate_targets(targets)

        # Compute default jobs
        if args.jobs is not None:
            max_jobs = args.jobs
        else:
            _logical_cores = os.cpu_count() or 4
            max_jobs = max(1, _logical_cores // 2)

        success = build_module.build_targets(
            targets=targets,
            output_dir=args.output_dir,
            sequence_mode=args.sequence,
            max_jobs=max_jobs,
            single_command=not args.parallel_formats,
            website=args.website,
            docs_root=docs_root,
        )
        sys.exit(0 if success else 1)

    elif args.command == "check":
        _setup_logging()
        from .check import run_check as check_fn
        docs_root = args.docs_root.resolve()
        _require_docs_root(docs_root, "check")
        success = check_fn(
            docs_root=docs_root,
            validate_only=args.validate_only,
            cleanup_uncited=args.cleanup_uncited,
        )
        sys.exit(0 if success else 1)

    elif args.command == "pre":
        _setup_logging()
        docs_root = args.docs_root.resolve()
        _require_docs_root(docs_root, "pre")

        config_path = docs_root / "build.yml"
        if config_path.exists():
            build_module.initialize_config(docs_root, config_path)

        build_module.run_pre_build_sequence(build_module.EXTERNAL_CONFIG, docs_root)
        sys.exit(0)

    elif args.command == "render":
        _setup_logging()
        from .utils.quick_render import (
            find_build_yml,
            load_exclude_patterns,
            resolve_and_render,
        )

        docs_root = args.docs_root.resolve()
        _require_docs_root(docs_root, "render")

        build_yml = find_build_yml(docs_root)
        exclude_patterns = (
            load_exclude_patterns(build_yml) if build_yml else []
        )

        success, _ = resolve_and_render(
            args.patterns,
            docs_root,
            prompt=not args.all,
            exclude_patterns=exclude_patterns,
            format=args.format,
        )
        sys.exit(0 if success else 1)

    elif args.command == "deploy":
        _setup_logging()

        docs_root = args.docs_root.resolve()
        _require_docs_root(docs_root, "deploy")
        success = deploy_module.run_deploy(
            docs_root,
            config_path=args.config,
            dry_run=args.dry_run,
            require_all=args.require_all,
            extra_plugin_dirs=args.plugin_path,
            timeout=args.timeout,
        )
        sys.exit(0 if success else 1)

    elif args.command == "plugins":
        _setup_logging()

        docs_root = args.docs_root.resolve()
        _require_docs_root(docs_root, "plugins")
        found = deploy_module.list_plugins(docs_root, args.plugin_path)
        if not found:
            print("No plugins found on the plugin path.")
            sys.exit(0)
        for manifest in found:
            print(f"{manifest.name}\t{manifest.path}\t{manifest.description}")
        sys.exit(0)

    elif args.command == "clean":
        _setup_logging()
        docs_root = args.docs_root.resolve()
        _require_docs_root(docs_root, "clean")
        success = build_module.clean_quarto_artifacts(docs_root)
        sys.exit(0 if success else 1)

    else:
        parser.print_help()
        sys.exit(1)


if __name__ == "__main__":
    main()
