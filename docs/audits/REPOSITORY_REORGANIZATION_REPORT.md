# Repository Reorganization Report

**Project:** AETHER
**Date:** 2026-11-05
**Target branch:** `architecture/repository-reorganization`
**Migration base:** `a50b265d187041f0491fdfad2b7c92ddd691fefb` (`main`)
**Baseline audit:** [REPOSITORY_REORGANIZATION_BASELINE.md](REPOSITORY_REORGANIZATION_BASELINE.md)

## Executive summary

The repository has been reorganized from a root-heavy collection of Python modules into a `src`-layout package, with tests, benchmarks, documentation, datasets, and results in dedicated areas. Historical results and phase reports were retained; source moves were made with `git mv` to preserve Git rename detection and history. The migration is isolated on `architecture/repository-reorganization`; it does not rewrite or merge the existing `phase8` branch.

The package targets Python 3.10+ and keeps its core Python runtime dependency-free. Platform-specific process metrics now use `src/aether/metrics.py`, replacing Unix-only assumptions with portable behavior. The Rust `ctypes` backend remains an on-demand, host-specific build and is never reused across operating systems or architectures. Root-level compatibility shims preserve legacy module imports and script entry points while new code uses `aether.*`.

## Repository structure and packaging

- Runtime package: `src/aether/`, with core, graph, reasoning, temporal, native, adapter, and resource modules.
- Test suite: `tests/`, organized into unit, integration, regression, and portability areas.
- Benchmarks: `benchmarks/`, grouped by baseline and phase, with shared path/resource discovery.
- Documentation: `docs/`, including phase records, development guides, and audit reports.
- Dataset metadata/resources: `src/aether/resources/datasets/`; externally sourced, large SNAP data remain outside version control.
- Historical outputs: `results/`, retained as historical records rather than overwritten by migration smoke tests.

`pyproject.toml` uses explicit setuptools `src`-layout package configuration and declares the legacy top-level modules as compatibility shims. The Rust source and dataset manifests are included as package resources. A wheel and source distribution were built; the wheel was installed into a separate target and exercised from a directory outside the checkout.

## Portability and compatibility

- CPU and memory metadata are collected through platform-aware helpers. Unavailable measurements are represented as unavailable rather than relying on Linux `/proc` or Unix `resource` imports.
- Native library filenames and compilation are selected for the current host. The packaged Rust source is compiled on demand to the user's cache and loaded through the existing FFI wrapper.
- Windows-sensitive cleanup and temporary-file handling were adjusted in the affected tests and benchmark teardown paths.
- Existing flat imports and documented root entry points are retained through shims; the package's internal imports use the namespaced `aether.*` layout.
- CI is configured for Python 3.10, 3.12, and 3.13 on Linux, macOS, and Windows (nine matrix jobs). The prior baseline had all three Windows jobs failing; matrix configuration itself is not proof of successful Windows support.

## Validation performed in this task

- `python3 -m unittest discover -s tests -v`: **133 tests passed** (3.109 seconds).
- Baseline benchmark smoke: 30 nodes, 60 initial edges, 30 updates, 50 queries, one repeat, seed 7; output directed to a fresh `/tmp` directory.
- Phase 2 smoke: **25 strategy runs, exact answers**; output directed to a fresh `/tmp` directory.
- Built both `aether_knowledge_prototype-0.1.0-py3-none-any.whl` and `aether_knowledge_prototype-0.1.0.tar.gz`.
- Installed wheel outside the repository and verified package imports, `DynamicGraph` API, benchmark imports, packaged Rust source, and packaged Phase 5 manifest.
- Compiled the Rust native library from the installed wheel and passed a `RustDynamicGraph` reachability check.
- Scanned relative Markdown links under `docs/`; no broken links remained after correcting the Phase 5 research link.
- `git diff --check` passed. Final setuptools build emitted no setuptools warnings.

These checks were executed on the current Linux sandbox; they do not substitute for the pending remote matrix or a native Windows/macOS environment.

## Branch separation and publication status

The architecture branch was created from `main` at `a50b265d187041f0491fdfad2b7c92ddd691fefb` and published at `1b96dc581beb464d659e7b99a3794772b0fae84d`. At publication, `origin/phase8` pointed to `2f46a0c4b0702419f8a0b2ed9a272ffdaa51b374`, seven commits ahead of `main`; it is a distinct ref. Phase 8 contains the reasoning/identity/proof-tracking implementation; this architecture branch contains the repository layout, packaging, portability, documentation, and CI reorganization and intentionally does not cherry-pick or merge the Phase 8 feature commits. Neither branch ref was rewritten by this migration.

**Remote CI status:** pushed; run [42095525749](https://github.com/kalyeltonvieira/Aether/actions/runs/42095525749) was still queued at the time of this report update. The workflow defines nine combinations: Linux, macOS, and Windows on Python 3.10, 3.12, and 3.13. Do not describe Windows compatibility as CI-verified until all Windows jobs pass.

## Known limitations

- Linux ARM64 was not a CI matrix target in the audited workflow; no ARM64-specific compatibility claim is made.
- Full SNAP datasets are external and are not bundled. Reproducing real-data benchmarks requires fetching the manifest-listed data and checking their recorded hashes.
- Legacy shims are intentionally retained for compatibility and can be deprecated only through a separately announced transition.
- Remote CI has not yet completed; check the linked Actions run for its final per-platform result.
