# Desenvolvimento no Windows 10/11 x86_64

1. Instale Python 3.10, 3.12 ou 3.13 e confirme `py -V`.
2. Para backend Rust, instale Rust 1.99.1 (rustup) e o linker C/C++ MSVC Build Tools compatível; confirme `rustc --version` e `where link`.
3. Crie/ative venv e instale `py -m pip install -e .`.
4. Rode `py -m unittest discover -s tests -v`.
5. Para compilar/testar biblioteca nativa: `py -c "from aether.native.bindings import compile_native; print(compile_native())"`.
6. Para benchmark curto, use seus argumentos de smoke e um novo `--out`; nunca sobrescreva os resultados versionados.

O nome do artefato é `.dll`. Se `rustc` ou linker falhar, a mensagem de compilação é erro, não fallback silencioso. O relatório final registrará a matriz efetivamente executada na branch; não interprete estas instruções como evidência de teste.
