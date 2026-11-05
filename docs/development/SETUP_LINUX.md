# Desenvolvimento Linux

1. Instale Python 3.10+ e, para backend nativo, Rust 1.99.1 e linker do sistema.
2. Crie ambiente virtual: `python3 -m venv .venv`; ative-o conforme seu shell.
3. Instale: `python -m pip install -e .`; rode `python -m unittest discover -s tests -v`.
4. Compile FFI: `python -c "from aether.native.bindings import compile_native; print(compile_native())"`.
5. Para reproduzir benchmarks, instale extras opcionais quando necessários; escolha `--out` novo e registre CPU, Python, Rust e hashes dos datasets.

A biblioteca nativa será `.so`. Linux x86_64 CI evidence will be listed in the migration report. Linux ARM64 requires a native/appropriate CI runner; until a real run is recorded, ARM64 remains unverified.
