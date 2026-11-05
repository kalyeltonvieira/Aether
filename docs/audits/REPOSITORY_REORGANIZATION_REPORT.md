# Repository Reorganization Report

**Project:** AETHER
**Date:** 2026-11-05
**Target branch:** `architecture/repository-reorganization`
**Migration base:** `a50b265d187041f0491fdfad2b7c92ddd691fefb` (`main`)
**Baseline audit:** [REPOSITORY_REORGANIZATION_BASELINE.md](REPOSITORY_REORGANIZATION_BASELINE.md)

## Executive summary

The repository has been reorganized from a root-heavy collection of Python modules into a `src`-layout package, with tests, benchmarks, documentation, datasets, and results in dedicated areas. Historical results and phase reports were retained; source moves were made with `git mv` to preserve Git rename detection and history. During PR conflict resolution, the branch was updated with the current `main` (which includes the Phase 8 merge) and the Phase 8 implementation, tests, benchmark, results, and reports were retained in the organized layout. The `phase8` branch ref itself was not rewritten.

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

- `python3 -m unittest discover -s tests -v`: **159 tests passed** (2.649 seconds), including the newly integrated Phase 8 tests.
- Baseline benchmark smoke: 30 nodes, 60 initial edges, 30 updates, 50 queries, one repeat, seed 7; output directed to a fresh `/tmp` directory.
- Phase 2 smoke: **25 strategy runs, exact answers**; output directed to a fresh `/tmp` directory.
- Phase 8 smoke: one contradictions workload/seed, eight measured rows, zero oracle mismatches; output directed to a fresh `/tmp` directory. The legacy `python3 phase8_bench.py` entry point and namespaced `python -m benchmarks.phase8.phase8_bench` were both verified.
- Built both `aether_knowledge_prototype-0.1.0-py3-none-any.whl` and `aether_knowledge_prototype-0.1.0.tar.gz`.
- Installed wheel outside the repository and verified package imports, `DynamicGraph` API, benchmark imports, packaged Rust source, and packaged Phase 5 manifest.
- Compiled the Rust native library from the installed wheel and passed a `RustDynamicGraph` reachability check.
- Scanned relative Markdown links under `docs/`; no broken links remained after correcting the Phase 5 research link.
- `git diff --check` passed. Final setuptools build emitted no setuptools warnings.

These checks were executed on the current Linux sandbox; the remote CI matrix result is recorded separately below.

## Branch separation and publication status

The architecture branch originated at `main` commit `a50b265d187041f0491fdfad2b7c92ddd691fefb`. PR #9 later merged Phase 8 into `main` at `31b73e2533dcb668c6d1849fc304bdee7ecd432c`, which is now the integration base for resolving PR #10. The architecture branch combines that mainline functionality with the repository layout, packaging, portability, documentation, and CI reorganization. The separate `phase8` branch remains unchanged; branch-specific commits are preserved and the architecture PR resolves against the updated base rather than rewriting either ref.

**Remote CI status:** run [42095865154](https://github.com/kalyeltonvieira/Aether/actions/runs/42095865154) passed **9/9 jobs** on the pre-merge architecture code, including all three Windows jobs. Because this conflict resolution incorporates the Phase 8 updates from current `main`, that earlier green run is not the final validation for the merged tree. The post-resolution CI result must be recorded after pushing the merge-resolution commit; do not treat the prior run as proof for the updated branch.

## Known limitations

- Linux ARM64 was not a CI matrix target in the audited workflow; no ARM64-specific compatibility claim is made.
- Full SNAP datasets are external and are not bundled. Reproducing real-data benchmarks requires fetching the manifest-listed data and checking their recorded hashes.
- Legacy shims are intentionally retained for compatibility and can be deprecated only through a separately announced transition.
