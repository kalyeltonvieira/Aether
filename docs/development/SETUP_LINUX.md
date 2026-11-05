# Desenvolvimento Linux

Use Python 3.10+, Node.js 22 LTS e pnpm na versão fixada em `frontend/package.json`. Rust 1.99.1 e um linker do sistema são necessários apenas para operações nativas. Clone a branch de trabalho publicada, não uma versão histórica de resultados.

```bash
python3 -m venv .venv
source .venv/bin/activate
python -m pip install --upgrade pip
python -m pip install -e ".[api]"
corepack enable
pnpm --dir frontend install --frozen-lockfile
python -m unittest discover -s tests -v
pnpm --dir frontend typecheck
pnpm --dir frontend test
pnpm --dir frontend build
```

Se você só precisa do núcleo, `python -m pip install -e .` continua sem dependência de FastAPI/Node. Para compilar/testar a FFI local:

```bash
python -c "from aether.native.bindings import compile_native; print(compile_native())"
```

A biblioteca nativa é `.so`, compilada para a arquitetura corrente; falha de compilação não é fallback silencioso. Linux ARM64 foi executado nesta sessão; o relatório final separa essa evidência de Linux x86_64/Windows em CI. Não extrapole um resultado entre arquiteturas nem copie o binário de outro host.

## API e frontend

```bash
bash scripts/dev-studio.sh
# Alternativa com dados de teste claramente rotulados, somente no store vazio:
bash scripts/dev-studio.sh --seed-fixture
```

Abra `http://localhost:3000`; API local fica em `127.0.0.1:8000`. O Vite encaminha REST/WebSocket. Login é obrigatório: configure `AETHER_OPERATOR_TOKEN` no servidor ou use o arquivo privado de token indicado no startup, sem copiar segredos para o frontend. Para processos separados, use `--api-only` e `--frontend-only`. Ctrl+C encerra ambos os filhos; não use vários workers da API no mesmo diretório de dados. Defaults de persistência ficam em `.aether-data/`, que é ignorado por Git. Nunca versionar token, cookies ou SQLite de execução.

No ambiente gerenciado use Manus OAuth e allowlist de operadores no servidor, com origem pública HTTPS explicitamente configurada; veja [Studio](WEB_STUDIO.md) e [API](../architecture/API.md). O modo local autenticado não é uma implantação durável em container.

## Benchmarks

Use um diretório novo em `results/evolution/`, registre SO/CPU/Python/Rust/hashes e preserve os históricos. O relatório [Eficiência](../architecture/EFFICIENCY.md) separa ganhos de joins seletivos das perdas do controller adaptativo; [Memória](../architecture/MEMORY.md) explica o orçamento de payload residente versus RSS do processo.
