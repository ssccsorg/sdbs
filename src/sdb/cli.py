"""
SDBS CLI — entry point for all sdb commands.

Subcommands:
  init     Scaffold a new docs directory with default templates.
  build    Build one or more Quarto targets.
  check    Validate links, citations, and cross-references.
  pre      Run pre-render steps (latest docs, path resolution, formatting).
"""

import argparse
import logging
import os
import sys
from pathlib import Path

from sdb import __version__

from . import build as build_module
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
        "Supports parallel execution, website mode, and intelligent caching.",
        epilog=(
            "Examples:\n"
            "  sdb build docs whitepaper\n"
            "  sdb build docs whitepaper proposal --website -j 4\n"
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
    build_parser.add_argument(
        "--website", action="store_true",
        help="Use Quarto website profile (isolated parallel rendering)",
    )
    build_parser.add_argument(
        "--publish", action="store_true",
        help=(
            "Generate publishable artifact bundle after build. "
            "Produces TeX sources, clean markdown, C2PA signing, and "
            "Bundle metadata in _publish/{target}/. "
            "Works with or without --website."
        ),
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
        "resolve relative paths and includes, and format QMD/MD files. "
        "These same steps run automatically before every build.",
    )
    pre_parser.add_argument(
        "docs_root",
        type=Path,
        nargs="?",
        default=Path("."),
        help="Path to the docs directory (default: current directory)",
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

        # Load config
        config_path = args.config
        if config_path is None:
            default_config = docs_root / "build.yml"
            if default_config.exists():
                config_path = default_config

        build_module.initialize_config(docs_root, config_path)

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
            publish=args.publish,
        )
        sys.exit(0 if success else 1)

    elif args.command == "check":
        _setup_logging()
        from .check import run_check as check_fn
        success = check_fn(
            docs_root=args.docs_root.resolve(),
            validate_only=args.validate_only,
            cleanup_uncited=args.cleanup_uncited,
        )
        sys.exit(0 if success else 1)

    elif args.command == "pre":
        _setup_logging()
        docs_root = args.docs_root.resolve()

        config_path = docs_root / "build.yml"
        if config_path.exists():
            build_module.initialize_config(docs_root, config_path)

        build_module.run_pre_build_sequence(build_module.EXTERNAL_CONFIG, docs_root)
        sys.exit(0)

    elif args.command == "clean":
        _setup_logging()
        docs_root = args.docs_root.resolve()
        success = build_module.clean_quarto_artifacts(docs_root)
        sys.exit(0 if success else 1)

    else:
        parser.print_help()
        sys.exit(1)


if __name__ == "__main__":
    main()
