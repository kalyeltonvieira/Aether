# Desenvolvimento e instalação

Requisitos de runtime: Python 3.10+. Rust 1.99.1 é opcional para o backend nativo. A fonte Python pode ser instalada sem compilador Rust; use um toolchain compatível quando compilar/usar FFI.

```bash
python -m venv .venv
# Ative o ambiente conforme o shell do sistema.
python -m pip install --upgrade pip
python -m pip install -e .
python -c "import aether; print(aether.__version__)"
python -m unittest discover -s tests -v
```

Para wheel/sdist: instale `build` e rode `python -m build`. Para ferramentas opcionais, `python -m pip install -e '.[plots]'` e/ou `python -m pip install -e '.[networkx]'`. Datasets SNAP grandes não fazem parte do pacote; consulte o manifesto e as licenças antes de baixar.
