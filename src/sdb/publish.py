"""SDBS publish — publishable artifact bundle generator."""

from __future__ import annotations
import logging, shutil, subprocess
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
    from sdb.build import EXTERNAL_CONFIG, TARGET_CONFIG
    if publish_dir is None:
        publish_dir = get_publish_dir(docs_root)
    if not targets:
        logger.info("No targets to publish.")
        return
    publish_cfg = external_config.get("publish", {})
    c2pa_enabled = publish_cfg.get("c2pa", {}).get("enabled", False)
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
        _capture_tex(qmd_path, bundle / "source", docs_root)
        _capture_md(qmd_path, bundle / f"{target}.md", docs_root)
        _copy_pdf(qmd_path, bundle / f"{target}.pdf", cfg, docs_root)
        _gen_metadata(qmd_path, bundle / "metadata.yaml", docs_root, target, cfg)
        if c2pa_enabled:
            logger.info("C2PA for %r not yet implemented (Phase 3).", target)
        nfiles = len(list(bundle.rglob("*")))
        logger.info("Bundle for %r assembled (%d files)", target, nfiles)
    if zenodo:
        logger.info("Zenodo upload not yet implemented (Phase 4).")


def _capture_tex(qmd_path: Path, dest: Path, docs_root: Path) -> None:
    logger.info("  TeX source -> %s", dest)
    try:
        r = subprocess.run(
            ["quarto", "render", str(qmd_path), "--to", "latex"],
            cwd=docs_root, capture_output=True, text=True, timeout=120,
        )
        if r.returncode != 0:
            logger.warning("  quarto render --to tex failed: %s", r.stderr[:300])
            return
    except Exception as e:
        logger.warning("  quarto render --to tex error: %s", e)
        return
    stem = qmd_path.stem
    parent = qmd_path.parent
    dest.mkdir(parents=True, exist_ok=True)
    copied = 0
    for pat, is_dir in [
        (f"{stem}.tex", False),
        (f"{stem}_files", True),
        ("*.bib", False),
        ("*.png", False),
        ("*.jpg", False),
        ("*.jpeg", False),
        ("*.svg", False),
        ("*.pdf", False),
    ]:
        tgt = parent / pat
        if is_dir:
            if tgt.exists() and tgt.is_dir():
                shutil.copytree(tgt, dest / pat, dirs_exist_ok=True)
                copied += 1
        elif "*" in pat:
            for f in parent.glob(pat):
                shutil.copy2(f, dest / f.name)
                copied += 1
        elif tgt.exists() and tgt.is_file():
            shutil.copy2(tgt, dest / pat)
            copied += 1
    freeze = docs_root / "_freeze" / stem
    if freeze.exists():
        for item in freeze.rglob("*"):
            rel = item.relative_to(freeze)
            (dest / "_freeze" / rel).parent.mkdir(parents=True, exist_ok=True)
            if item.is_file():
                shutil.copy2(item, dest / "_freeze" / rel)
    logger.info("  Copied %d source item(s)", copied)


def _capture_md(qmd_path: Path, out: Path, docs_root: Path) -> None:
    logger.info("  Markdown -> %s", out)
    try:
        r = subprocess.run(
            ["quarto", "render", str(qmd_path), "--to", "gfm"],
            cwd=docs_root, capture_output=True, text=True, timeout=120,
        )
        if r.returncode != 0:
            logger.warning("  quarto render --to gfm failed: %s", r.stderr[:300])
            return
    except Exception as e:
        logger.warning("  quarto render --to gfm error: %s", e)
        return
    stem = qmd_path.stem
    gen = qmd_path.parent / f"{stem}.md"
    if gen.exists():
        shutil.copy2(gen, out)
        gen.unlink(missing_ok=True)
    gf = qmd_path.parent / f"{stem}_files"
    if gf.exists():
        shutil.rmtree(gf, ignore_errors=True)


def _copy_pdf(qmd_path: Path, out: Path, cfg: Dict[str, Any], docs_root: Path) -> None:
    stem = qmd_path.stem
    cands = [
        docs_root / "_site" / f"{stem}.pdf",
        qmd_path.parent / f"{stem}.pdf",
    ]
    for c in cands:
        if c.exists() and c.stat().st_size > 0:
            shutil.copy2(c, out)
            logger.info("  PDF %s -> %s", c.name, out)
            return
    logger.warning("  No PDF for %s (looked: %s)", stem, cands)


def _gen_metadata(
    qmd_path: Path, out: Path, docs_root: Path, target: str, cfg: Dict
) -> None:
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
        "description": zm.get("description") or desc or f"SDBS publish bundle for {target}",
        "access_right": zm.get("access_right", "open"),
        "license": zm.get("license", "CC-BY-4.0"),
        "keywords": zm.get("keywords") or kw,
    }
    if "upload_type" in zm:
        meta["upload_type"] = zm["upload_type"]
    import yaml
    with open(out, "w", encoding="utf-8") as f:
        yaml.dump(meta, f, default_flow_style=False, allow_unicode=True, sort_keys=False)
    logger.info("  metadata.yaml written for %r", target)
