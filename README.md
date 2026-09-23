# SDBS

General Purpose SSCCS Technical Documentation Build System

- A high-level orchestration layer for docs generation solutions (currently Quarto-driven).

## Quick Start

### With pip

```bash
pip install sdb
sdb init docs
sdb build docs --website
```

### With Docker

```bash
docker pull ghcr.io/ssccsorg/sdbs:latest
docker run --rm -v $(pwd)/docs:/work -w /work ghcr.io/ssccsorg/sdbs:latest sdb build docs --website
```

### Try the example project

```bash
git clone https://github.com/ssccsorg/sdbs.git
cd sdbs
./examples/build.sh quickstart
```

This installs SDBS from source (or uses Docker if Quarto is not available) and builds
the `examples/quickstart/` project — a minimal documentation site with a landing page,
a getting-started guide, and an API reference.

## CLI Reference

```bash
# Scaffold a new docs directory
sdb init docs
sdb init docs --template ssccs     # with SSCCS-specific templates

# Build all targets
sdb build .
sdb build . --website -j 4         # parallel website build

# Pre-render steps (latest docs, path resolution, footnote cleanup, formatting, metadata)
sdb pre docs

# Validate links and citations
sdb check .

# Render a single document by short name for quick preview
sdb render map
sdb render map --to pdf            # render to a specific format

# Render and collect PDF artifacts (PDF, LaTeX, figures, media)
sdb pub map
sdb pub map --all                  # render all matches without prompting

# Remove Quarto build artifacts (_cached/, _files/, html, pdf...)
sdb clean docs
```

## Pre-build Sequence

`pre` and every `build` invoke the same built-in pre-build sequence before rendering. The sequence runs in five phases.

- Latest docs: regenerate `_include/_updated_docs_list.qmd` from git-tracked documents.
- Path resolution: resolve relative asset paths and includes across QMD and MD files.
- Footnote deduplication: in each `.qmd`, remove every use of a footnote tag after the first. Footnote definitions, YAML front matter, fenced code blocks, inline code spans, and escaped references are preserved.
- Formatting: run `rumdl fmt` with MD036 disabled.
- Metadata: write the `_metadata.tex` a document references from its PDF or beamer header, taking the values from the document's front matter and the files it lists under `metadata-files:`. A header that names a metadata macro without referencing a generated file has that reference inserted, which repairs the inconsistency that otherwise reaches LuaLaTeX as an undefined control sequence. It runs last so the version stamp covers the text after resolution and formatting, writes only when the target is missing or older than its inputs, and reports a document whose header offers no line to edit.

The sequence is idempotent. Running `sdb pre docs` on an already-clean tree changes nothing. Documents rendered through `sdb render` or `sdb pub` skip this sequence, since those commands call the underlying renderer directly without preprocessing. They do write the metadata file for the documents they select, and insert the reference a header needs, because the renderer reads that file from the document header and a preview of a new document would otherwise fail on a missing input.

## Documentation

- [SDBS](https://docs.ssccs.org/projects/sdbs/index.html): the project index, covering the build architecture, the parallel build model, and the LLMs pipeline.
- [Single-Path Artifact Pipeline](https://docs.ssccs.org/projects/sdbs/ci_observations.html): one container image carrying emulation, RTL verification, and documentation, with the agent knowledge base extracted from the same build.
- [The Living Corpus](https://docs.ssccs.org/projects/sdbs/knowledge_base_vision.html): SDBS as the knowledge-ization engine, from document corpus to living knowledge.

## Development

### Setup

```bash
git clone https://github.com/ssccsorg/sdbs.git
cd sdbs
pip install -e .
```

### Run tests

```bash
python -m pytest tests/ -v
```

### Build the Docker image

```bash
docker build -t ghcr.io/ssccsorg/sdbs:latest .
```

## License

Apache 2.0
