# SDBS

SSCCS Documentation Build System — a portable Quarto orchestration layer.

## Installation

```bash
pip install sdb
```

Or with uv:

```bash
uv tool install sdb
```

## Usage

```bash
# Scaffold a new docs directory
sdb init docs

# Build all targets
sdb build .

# Build with website profile (parallel)
sdb build . --website -j 4

# Validate links and citations
sdb check .

# Resolve broken paths and includes
sdb resolve .
```

## Quick Start with Docker

```bash
docker pull ghcr.io/ssccsorg/sdbs:latest
docker run --rm -v $(pwd)/docs:/work -w /work ghcr.io/ssccsorg/sdbs:latest sdb build docs --website
```

## License

Apache 2.0
