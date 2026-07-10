# Default publish sequence (runs only when --publish is set)
# Each entry is a callable(docs_root, ...) or a subprocess command list.
# Will be populated in Phase 2 when publish.py is implemented.
_DEFAULT_POST_PUBLISH: List = []


def run_publish_sequence(
    external_config: Dict[str, Any],
    docs_root: Path,
    targets: Optional[List[str]] = None,
    publish_dir: Optional[Path] = None,
    zenodo: bool = False,
    zenodo_sandbox: bool = False,
) -> None:
    """Run publish post-jobs: TeX capture, pub.md, C2PA signing, bundle assembly.

    This sequence runs after the full post-render sequence when ``--publish``
    is enabled. Default steps are defined in ``_DEFAULT_POST_PUBLISH``.
    """
    logger.info("Running publish post-job sequence...")
    _run_default_sequence(_DEFAULT_POST_PUBLISH, docs_root, "Publish")
    if zenodo:
        logger.info(
            "Zenodo upload requested (sandbox=%s). "
            "Upload logic will be implemented in a future phase.",
            zenodo_sandbox,
        )