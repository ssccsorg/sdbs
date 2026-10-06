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
sdb build .                        # the formats each target declares
sdb build . --website -j 4         # parallel website build
sdb build . --article              # article output, assembled for publication

# Pre-render steps (latest docs, path resolution, footnote cleanup, formatting, metadata)
sdb pre docs

# Validate links and citations
sdb check .

# Render a single document by short name for quick preview
sdb render docs map
sdb render docs map --to pdf       # render to a specific format

# Upload built artifacts to an external deploy channel
sdb deploy docs
sdb deploy docs --require-all
sdb deploy docs --dry-run

# Remove Quarto build artifacts (.sdbtmp_*, _files/, html, pdf...)
sdb clean docs
```

Every command that operates on a project takes the directory as its first positional argument: `init` takes the directory to scaffold, `build`, `check`, `pre`, `render`, and `clean` take the docs root the documents live in, and `deploy` and `plugins` take the directory holding `_deploy.yml`.

Every command that takes a docs root stops when the path is not a directory, and names the path it rejected. A command that would otherwise walk no documents and report success fails instead, so a typo or a wrong working directory is visible where it happens rather than later as a render error in a document that was never processed.

## Build Outputs

`build` renders the targets it is given in one of two named outputs, or in the formats each target's own configuration declares when neither is named.

`--website` renders the Quarto website profile. It owns the site directory (`_site` by default, or `--output-dir`), and it clears that directory before it renders, so a website build replaces the site rather than adding to it.

`--article` renders the PDF form of each target and assembles the distribution an article is published as: the PDF, its LaTeX source, the figures, the media, and the shared `_files`. Each document's distribution is a directory named after it, beside the document itself, or under `--output-dir` when one is given. It is the form an external deploy channel carries, which is what lets a Zenodo-style channel be added as a plugin: `sdb build docs --article` produces the article, and a deploy activation names the directory it publishes.

An article build goes through the renderer rather than through the site orchestration, since an article is a document's publication artifact rather than a page. It therefore neither reads nor writes the site directory, and `--sequence`, `--jobs`, `--parallel-formats`, and the `snapshot` target do not apply: the article is rendered document by document, and `sdb build` refuses those rather than ignoring them. The built-in pre-build sequence does run, so the version stamp an article carries agrees with the one a full build writes for the same document.

## Build Cache

A build keeps the rendered form of each document in `.sdbtmp_cache`, under the target name the document has, so an unchanged document is not rendered twice, and it runs the Jupyter cache Quarto executes notebooks against in `.sdbtmp_jupyter`.

The directory a target is named by holds the record of what each of its formats was rendered from, beside the rendered artifacts themselves, so one name identifies a document everywhere and nothing the build caches sits beside a source file.

Both live in the directory the command was run from. That is one place whether the documents sit in a subdirectory or the docs root is the repository root, so a workflow caches `.sdbtmp_cache` and `.sdbtmp_jupyter` at its checkout root in either case, and nothing the build writes sits outside the tree it checked out.

Every folder the build writes for itself carries one marker, `.sdbtmp_`: the cache, the Jupyter cache, and the record a target's formats are named by. The one folder that cannot carry it is `_sdbtmp_build`, the scratch space a parallel website build copies the tree into. A project's own folders are named `_include`, `_extensions`, `_files` and the like, so the marker tells the build's own apart from a project's wherever a folder is listed. The engine reads no folder that carries it: target discovery excludes it, the isolated copy a website build renders from leaves it behind, `sdb clean` removes it, and a preview does not find one document twice. A project whose docs root is its repository root therefore declares nothing for them.

That exception is a constraint rather than a preference. The scratch directory is the parent of the document Quarto is given, and Quarto resolves a project through the path of that document. A hidden component stops the search, and Quarto then renders the document on its own, so a website build loses the site directory and every file the website writes for a page. Measured on the Quarto the image pins, 1.9.35, over the ssccs corpus: with `_sdbtmp_build` the build cached a site directory for each of its 112 targets and the post-render step collected llms.txt from them, and with `.sdbtmp_build` every target reported no site directory and the post-render step had nothing to collect. The caches are never on an input's ancestry, so a hidden name is safe for them.

The copy a target renders from lives in the scratch directory and is removed when the build finishes, so a workflow never caches it. What a workflow caches is the two caches the command wrote, which is the pair named above.

## External Deploy Plugins

`sdb deploy` runs the plugins a project activates. A plugin is an external tool, unrelated to sdbs: sdbs carries no plugin code and imports no plugin. It reads a manifest at the plugin's root, runs its command, and reads the result.

A plugin lives in its own directory with a `manifest.yml` at that root:

```yaml
manifest: 1
name: s3
description: Upload an artifact directory to an S3-compatible object store
command: [python3, __main__.py]
interface:
  artifact: directory
  options: [bucket, prefix, endpoint, region, delete, allow_unscoped_delete, auth]
```

`manifest` is the schema version, `name` is the name an activation refers to, and `command` is the program and its arguments. `env` is optional and is merged into the plugin's environment. `interface` is optional and states the kind of path the plugin takes in `artifact` and the option names it accepts in `options`; the manifest is the source of truth for what a plugin declares.

The project that uses sdbs activates a plugin in `_deploy.yml` at its root:

```yaml
deploy:
  - plugin: s3
    documents: [pdf, c2pa]
    options:
      bucket: example-private
      prefix: project/docs
      auth:
        mode: access
        domain: https://private.example.com
```

An activation declares what it publishes in exactly one of two ways. `artifact` is a directory to upload, resolved against the directory holding `_deploy.yml`. `documents` is the list of extensions to select out of the build output, which is what a site build produces around a page: the selection takes `_site/**/*.pdf` and `_site/**/*.c2pa`, and skips any path inside a page's asset directory (`site_libs/`, `*_files/`), since a document that lands there belongs to the page rather than to the channel. `source` names that build output when it is not `_site`.

The engine composes the selection, not the project. It copies the selected documents into a directory it owns, hands that directory to the plugin as the artifact, and removes it when the activation finishes. The render owns the build output, and a deploy container mounts the tree read-only, so nothing is written back into the project or left behind by a deploy.

Naming both, or neither, fails the run, as does a `documents` list that is empty, or that names something other than an extension. A `source` without `documents` fails too, since nothing would read it. `documents` and `source` compose the artifact rather than reaching the plugin, so they are not activation options and the manifest does not declare them.

A named plugin that is not found is skipped, since a plugin is optional; set `require: true` on the activation, or pass `--require-all`, to make a missing plugin fail instead.

An activation option the manifest does not declare in `options` fails the run, so a typo is reported rather than passed to a plugin that ignores it. A manifest with no `interface`, or an `interface` with no `options`, declares nothing and accepts any option, while `options: []` declares that it takes none.

Each plugin is given a bounded time to return, by default 900 seconds, which `--timeout` overrides.

The plugin path is the directories searched for manifests, in order, first match wins: the `--plugin-path` values, then `SDB_PLUGIN_PATH`, then `<docs_root>/plugins`. `<docs_root>` is the directory passed to `sdb deploy`, so a project ships its own plugin at `<docs_root>/plugins/<name>/manifest.yml`, beside the `_deploy.yml` that activates it:

```
docs/
  _deploy.yml
  _site/
  plugins/
    mychannel/
      manifest.yml
```

A `--config` file elsewhere moves the activation and the artifact it names, while the local plugin directory stays with the docs root. A plugin is a direct child of one of those directories, and one whose manifest cannot be read is reported and skipped, so a broken plugin does not stop the others. An explicit location beats the convention, so a deployment that sets `SDB_PLUGIN_PATH` replaces a plugin the project ships under the same name, which is what lets the image supply a reference plugin and a consumer override it. `sdb plugins` lists what it finds.

Across the process boundary the contract is one JSON request on the plugin's stdin and one JSON result on its stdout, with the exit code carrying success or failure:

```json
{"deploy": 1, "plugin": "s3", "artifact": "/abs/path", "options": {}, "dry_run": false}
{"deploy": 1, "ok": true, "uploaded": 164, "deleted": 0, "urls": [], "message": ""}
```

The engine reads `deploy`, `ok`, `uploaded`, `deleted`, `urls`, and `message` from the result, and logs each entry in `urls`.

The endpoint, the region, and the credentials travel in the environment, never on the command line or in the request, so a provider's values and its secrets stay with the project that deploys.

Deploy runs as its own invocation, separate from the render. The render container executes project-controlled Quarto and Jupyter code, so it stays free of upload credentials; the deploy invocation receives the credentials and runs a plugin, which is a tool rather than project code.

### The s3 plugin

`plugins/s3` is a reference plugin. It uploads an artifact directory to an S3-compatible object store and names the S3 protocol rather than a provider. Its `options` are:

- `bucket` (required) and `prefix`.
- `endpoint` (or `S3_ENDPOINT`) and `region` (or `AWS_REGION`).
- `delete` mirrors the artifact, removing remote keys absent from it. It needs a `prefix`, or `allow_unscoped_delete`, because a delete at the bucket root would remove every object outside the artifact.
- `auth.mode` records how a client reaches the deployed tree. `none` reports nothing. `access` reports the `domain`, expected to sit behind an authenticated edge such as an identity-aware proxy or an SSO gate, which authorizes every request and keeps a website's relative links working. `presigned` mints a time-limited GET URL for each path in `objects`, valid for `expires_seconds`, on the store endpoint, which fits a single file.

Credentials come from `AWS_ACCESS_KEY_ID` and `AWS_SECRET_ACCESS_KEY`. The plugin sends no object ACL, so an object is private unless the bucket itself is exposed, which is a provider setting outside this tool.

The plugin signs its requests with the standard library rather than a cloud SDK. `tests/test_s3sig.py` pins the signer against the published AWS SigV4 vectors, so a wrong canonical request fails a test instead of a deploy.

### Writing a plugin

A plugin is a program in any language. Put a `manifest.yml` at its root, read the one JSON request from stdin, write one JSON result to stdout, and exit non-zero on failure. The command runs with the plugin's own directory as its working directory, so a plugin may keep its modules beside its manifest and reach them by name. The s3 plugin under `plugins/s3` is a complete example: `manifest.yml`, `__main__.py` for the stdio contract, and `channel.py` for the work, with `client.py` and `signer.py` beside them.

## Pre-build Sequence

`pre` and every `build` invoke the same built-in pre-build sequence before rendering. The sequence runs in five phases.

- Latest docs: regenerate `_include/_updated_docs_list.qmd` from git-tracked documents.
- Path resolution: resolve relative asset paths and includes across QMD and MD files.
- Footnote deduplication: in each `.qmd`, remove every use of a footnote tag after the first. Footnote definitions, YAML front matter, fenced code blocks, inline code spans, and escaped references are preserved.
- Formatting: run `rumdl fmt` with MD036 disabled.
- Metadata: write the `_metadata.tex` a document references from its PDF or beamer header, taking the values from the document's front matter and the files it lists under `metadata-files:`. The step heals the mismatches between those declarations and what the render needs. A header that names a metadata macro without referencing a generated file gets that reference inserted, which is the inconsistency that would otherwise reach LuaLaTeX as an undefined control sequence. An `affiliations` entry that declares no url or domain gets the key supplied in the `metadata-files` entry that declares it, which is what the `\href` on the title page reads; a document that declares the affiliation in its own front matter is reported and left alone. An incomplete affiliation renders an empty link rather than failing, so that case reports it. The generated file itself is written when it is missing or older than its inputs. It runs last so the version stamp covers the text after resolution and formatting, and it reports a document whose header offers no line to edit. Every case is named, so one can be switched off on its own under `metadata.disabled` in `build.yml`, and `metadata.report_only` turns every repair off at once.

The sequence is idempotent. Running `sdb pre docs` on an already-clean tree changes nothing. Documents rendered through `sdb render` skip this sequence, since that command calls the underlying renderer directly without preprocessing. It does run the metadata step for the documents it selects, which writes the file a header consumes, inserts the reference a header needs, puts an unguarded input behind `\IfFileExists`, and supplies the affiliation keys a header links with, because the renderer reads that file from the document header and a preview of a new document would otherwise fail on a missing input. A preview can therefore edit the document it selects, which it did not before.

### Metadata Cases

The metadata step works through a named list of inconsistencies between a document's declarations and what the render needs. Each case is switched on its own under `metadata:` in `build.yml`, so a finding can be silenced or a repair held back without turning the step off.

```yaml
metadata:
  disabled: [affiliation-blank]   # case names to switch off; a typo is reported
  report_only: false              # report every finding and write nothing
```

- `document-outside-root`: a document that resolves out of the docs root is skipped, which is what a symlinked document looks like.
- `input-missing`: a header input that does not exist and whose name does not follow the `*_metadata.tex` convention is reported, since nothing here creates it.
- `reference-missing`: a header that names a generated macro with no reference gets the reference inserted behind `\IfFileExists`, and a header with no editable line is reported.
- `reference-unguarded`: an input that is not behind `\IfFileExists` is put there, with the macros the header uses declared empty, so a render that never reaches sdbs compiles; a reference in a form the step cannot rewrite is reported.
- `invalid-front-matter`: front matter that does not parse stops generation for that document rather than writing a file of empty macros.
- `declared-metadata-missing`: a `metadata-files` entry the tree does not carry is reported and skipped.
- `affiliation-url-from-author-key`: an affiliation with no url takes the url the same author entry declares at author level.
- `affiliation-url-from-domain`: an affiliation with no url takes its domain with the `https://` scheme.
- `affiliation-domain-from-url`: an affiliation with no domain takes the host of its url.
- `affiliation-blank`: an affiliation whose url or domain a header links with, and that nothing can supply, is reported; the declaration is left alone.
- `reference-outside-root`: a reference that resolves out of the docs root is reported per target and left alone.
- `shared-target`: several documents referencing one generated file is reported once, with the document that supplies the stamp.
- `metadata-file-missing-or-stale`: the generated file is written when it is missing or older than the document and its `metadata-files`.

A repair that a disabled case depends on is held back with it, so the affiliation keys are supplied together or not at all.

A new case has to reach every list that names the cases: the `CASE_*` constant, `CASE_ORDER`, the ordering block in `src/sdb/utils/metadata.py`, the inventory comment in both `src/sdb/templates/*/build.yml`, and the list above. `TestCaseInventory` in `tests/test_metadata.py` compares each of them against `CASE_ORDER`, so a list left behind fails the suite rather than leaving a case that no reader can find.

The contract the step judges is the macro list its generator writes. A header is examined for those names and for the reference that gives them a path into the document, and for nothing else, so a header that names a command the generator does not declare passes in silence. A passing step is a statement about the metadata contract, and not about a document's LaTeX.

A header may guard the input with `\IfFileExists` and declare the macros it uses in the other branch. sdbs supplies the values, and a render that never reaches sdbs compiles with them empty rather than failing on an absent file. The reference repair inserts that guarded form, so a document the step repairs keeps rendering without sdbs.

The sequence tolerates a step that fails, because an absent optional tool must not fail a build. It logs a count when it finishes, such as `Pre-build: 4 of 4 step(s) completed`, and a step that raised or exited non-zero is named in that line. A skipped step is named too, since a tool missing from `PATH` is normal rather than a failure.

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
