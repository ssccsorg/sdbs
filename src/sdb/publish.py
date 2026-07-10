import os, shutil, subprocess, logging
from pathlib import Path
from typing import Any, Dict, List, Optional

logger = logging.getLogger(__name__)
PUBLISH_DIR_NAME = "_publish"


def get_publish_dir(docs_root: Path) -> Path:
    return docs_root / PUBLISH_DIR_NAME


def run_publish_sequence(
    external_config: Dict[str, Any],
    docs_root: Path,
    targets: Optional[List[str]] = None,
    publish_dir: Optional[Path] = None,
    zenodo: bool = False,
    zenodo_sandbox: bool = False,
) -> None:
    from sdb.build import TARGET_CONFIG
    if publish_dir is None:
        publish_dir = get_publish_dir(docs_root)
    if not targets:
        logger.info("No targets to publish.")
        return

    for target in targets:
        cfg = TARGET_CONFIG.get(target)
        if cfg is None:
            logger.warning("Target %r not in TARGET_CONFIG, skipping.", target)
            continue
        qmd_rel = cfg.get("qmd")
        if not qmd_rel:
            continue
        qmd_path = docs_root / qmd_rel
        if not qmd_path.exists():
            logger.warning("QMD not found: %s, skipping.", qmd_path)
            continue

        bundle = publish_dir / target
        bundle.mkdir(parents=True, exist_ok=True)
        logger.info("Publishing %r -> %s", target, bundle)

        # Copy source context preserving relative paths
        _copy_source_context(qmd_path, bundle, docs_root)

        # Capture generated artifacts (tex, pdf, md)
        _capture_artifact_tex(qmd_path, bundle, docs_root)
        _capture_artifact_md(qmd_path, bundle, docs_root)
        _copy_artifact_pdf(qmd_path, bundle, docs_root)
        _copy_artifact_html(qmd_path, bundle, docs_root)

        # Metadata
        _gen_metadata(qmd_path, bundle / "metadata.yaml", docs_root, target)

        nfiles = len(list(bundle.rglob("*")))
        logger.info("Bundle for %r assembled (%d files)", target, nfiles)

    if zenodo:
        logger.info("Zenodo upload not yet implemented (Phase 4).")


def _copy_source_context(qmd_path: Path, bundle: Path, docs_root: Path) -> None:
    """Copy the QMD's directory context preserving relative paths.

    Includes:
      - The QMD source file itself
      - _include/ directory (referenced by Quarto includes)
      - .bib files alongside the QMD
      - Images alongside the QMD
      - Any _extensions/ referenced by the project
    """
    stem = qmd_path.stem
    parent = qmd_path.parent
    copied = 0

    # 1) Quarto metadata _files/ (referenced by \input{_files/...} in .tex)
    meta_dir = parent / "_files"
    if meta_dir.exists() and meta_dir.is_dir():
        shutil.copytree(meta_dir, bundle / "_files", dirs_exist_ok=True)
        copied += 1

    # 2) .bib, images from QMD's parent directory
    for pat in ["*.bib", "*.png", "*.jpg", "*.jpeg", "*.svg"]:
        for f in parent.glob(pat):
            shutil.copy2(f, bundle / f.name)
            copied += 1

    # (Quarto config files intentionally excluded; they are not
    #  part of the publish artifact and would mislead consumers.)

    logger.info("  Source context: %d item(s)", copied)


def _capture_artifact_tex(qmd_path: Path, bundle: Path, docs_root: Path) -> None:
    """Package .tex and all discoverable figure assets into the bundle.

    Searches in priority order:
      1. ``_publish/.staging/{target}/{stem}_files/`` (captured during build)
      2. ``_cached/{target}/*/{stem}_files/`` (cache-hit restore)
      3. ``{qmd_dir}/{stem}_files/`` (fresh render)
      4. ``_freeze/{stem}/{stem}_files/`` (Quarto cache)
      5. ``_site/{qmd_rel_dir}/{stem}_files/`` (website output)
    """
    stem = qmd_path.stem
    parent = qmd_path.parent

    # 1) .tex
    for src in [
        parent / f"{stem}.tex",
        docs_root / "_freeze" / stem / f"{stem}.tex",
    ]:
        if src.exists() and src.stat().st_size > 0:
            shutil.copy2(src, bundle / f"{stem}.tex")
            logger.debug("  TeX from %s", src)
            break

    # 2) Collect all possible _files/ sources
    sources = [bundle.parent / ".staging" / f"{stem}_files",
               parent / f"{stem}_files",
               docs_root / "_freeze" / stem / f"{stem}_files"]
    try:
        rel = qmd_path.relative_to(docs_root)
        sources.append(docs_root / "_site" / rel.parent / f"{stem}_files")
    except ValueError:
        pass
    cache_base = docs_root.parent / "_cached"
    if cache_base.exists():
        for ct in cache_base.iterdir():
            if ct.is_dir():
                for ch in ct.iterdir():
                    cf = ch / f"{stem}_files"
                    if cf.exists() and cf.is_dir():
                        sources.append(cf)

    # 3) Copy first-found (deduplicated by resolved path)
    seen = set()
    for src in sources:
        if src is None or not src.exists() or not src.is_dir():
            continue
        resolved = str(src.resolve())
        if resolved in seen:
            continue
        seen.add(resolved)
        shutil.copytree(src, bundle / src.name, dirs_exist_ok=True)
        logger.debug("  %s -> bundle", src.name)

def _site_path(qmd_path: Path, docs_root: Path, stem: str, ext: str) -> Path:
    """Return ``_site/{qmd_rel_dir}/{stem}.{ext}`` or empty Path if not under docs_root."""
    try:
        rel = qmd_path.relative_to(docs_root)
        return docs_root / "_site" / rel.parent / f"{stem}.{ext}"
    except ValueError:
        return Path()

def _capture_artifact_md(qmd_path: Path, bundle: Path, docs_root: Path) -> None:
    """Capture .md: from _llms/ or _site/ first, fallback to --to gfm."""
    stem = qmd_path.stem

    for src in [
        docs_root / "_llms" / f"{stem}.llms.md",
        docs_root / "_site" / f"{stem}.llms.md",
        _site_path(qmd_path, docs_root, stem, "llms.md"),
        _site_path(qmd_path, docs_root, stem, "llms.html"),
    ]:
        if src.exists():
            shutil.copy2(src, bundle / f"{stem}.md")
            logger.info("  MD from %s", src.parent.name)
            return

    logger.debug("  No .llms.md found (expected if --website was not used)")


def _copy_artifact_pdf(qmd_path: Path, bundle: Path, docs_root: Path) -> None:
    """Copy PDF from _site/ or QMD dir."""
    stem = qmd_path.stem
    for src in [
        docs_root / "_site" / f"{stem}.pdf",
        _site_path(qmd_path, docs_root, stem, "pdf"),
        qmd_path.parent / f"{stem}.pdf",
    ]:
        if src.exists() and src.stat().st_size > 0:
            shutil.copy2(src, bundle / f"{stem}.pdf")
            logger.info("  PDF %s", src.name)
            return
    logger.debug("  No PDF (expected for HTML-only)")


def _copy_artifact_html(qmd_path: Path, bundle: Path, docs_root: Path) -> None:
    stem = qmd_path.stem
    for src in [
        docs_root / "_site" / f"{stem}.html",
        _site_path(qmd_path, docs_root, stem, "html"),
        qmd_path.parent / f"{stem}.html",
    ]:
        if src.exists() and src.stat().st_size > 0:
            shutil.copy2(src, bundle / f"{stem}.html")
            logger.info("  HTML %s", src.name)
            return
    logger.debug("  No HTML (unexpected)")


def _gen_metadata(qmd_path: Path, out: Path, docs_root: Path, target: str) -> None:
    from sdb.build import EXTERNAL_CONFIG
    zm = EXTERNAL_CONFIG.get("publish", {}).get("zenodo", {}).get("metadata", {})

    title = target.capitalize()
    creators = [{"name": "SSCCS Foundation"}]
    desc = ""
    kw = ["sdbs", "ssccs"]

    try:
        text = qmd_path.read_text(encoding="utf-8")
        if text.startswith("---"):
            end = text.find("---", 3)
            if end > 0:
                for line in text[3:end].split("\n"):
                    s = line.strip()
                    if s.startswith("title:"):
                        title = s.split(":", 1)[1].strip().strip("\"'")
                    elif s.startswith("author:"):
                        a = s.split(":", 1)[1].strip().strip("\"'")
                        if a:
                            creators = [{"name": a}]
                    elif s.startswith("abstract:"):
                        desc = s.split(":", 1)[1].strip().strip("\"'")
    except Exception:
        pass

    meta = {
        "title": zm.get("title") or title,
        "creators": zm.get("creators") or creators,
        "description": zm.get("description") or desc or f"SDBS bundle: {target}",
        "access_right": zm.get("access_right", "open"),
        "license": zm.get("license", "CC-BY-4.0"),
        "keywords": zm.get("keywords") or kw,
    }
    if "upload_type" in zm:
        meta["upload_type"] = zm["upload_type"]

    import yaml
    with open(out, "w", encoding="utf-8") as f:
        yaml.dump(meta, f, default_flow_style=False, allow_unicode=True, sort_keys=False)
    logger.info("  metadata.yaml")
