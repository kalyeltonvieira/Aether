# Desenvolvimento no Windows 10/11 x86_64

Instale Python 3.10, 3.12 ou 3.13, Node.js 22 LTS e a versão pnpm fixada em `frontend/package.json`. Para Rust, instale Rust 1.99.1 por rustup e MSVC Build Tools/linker compatível; confirme `rustc --version` e `where.exe link`. O núcleo Python funciona sem compilar Rust; operações nativas exigem o toolchain completo.

No PowerShell, na raiz do checkout:

```powershell
py -m venv .venv
.\.venv\Scripts\Activate.ps1
python -m pip install --upgrade pip
python -m pip install -e ".[api]"
corepack enable
pnpm --dir frontend install --frozen-lockfile
python -m unittest discover -s tests -v
pnpm --dir frontend typecheck
pnpm --dir frontend test
pnpm --dir frontend build
python -c "from aether.native.bindings import compile_native; print(compile_native())"
```

Se a política do seu computador proíbe scripts, use o executável Python da venv diretamente; não altere políticas globais apenas para rodar o projeto. A FFI escolhe `.dll`; um erro de linker/compilação deve ser corrigido e não mascarado. Não copie `.so`/`.dylib` para Windows.

## Inicialização

```powershell
.\scripts\dev-studio.ps1
# Opcional: fixture real de teste, somente num store vazio:
.\scripts\dev-studio.ps1 --seed-fixture
# Alternativa sem executar um script PowerShell:
python scripts/run_studio.py
```

Abra `http://localhost:3000`. O launcher usa paths relativos ao próprio checkout, inicia API em loopback e encaminha REST/WebSocket pelo Vite. Login é obrigatório: configure `AETHER_OPERATOR_TOKEN` no servidor ou use o arquivo de token privado informado no startup; o valor nunca vai para o código cliente. `--api-only`/`--frontend-only` separam processos. Ctrl+C encerra os filhos. O diretório `.aether-data/` não deve ser commitado, especialmente seu token.

## Evidência de compatibilidade

A existência dessas instruções não demonstra execução aprovada no Windows 10/11. O relatório de entrega registra o runner Windows efetivamente usado pela CI e seus resultados de instalação, testes Python/FFI/API, build/testes frontend e fluxo integrado. Runner Windows Server, quando usado por `windows-latest`, não é teste de GUI em Windows 10/11. Linux ARM64 foi validado diretamente na sessão; versões de SO diferentes devem permanecer separadas no relatório. Consulte [Studio](WEB_STUDIO.md), [API](../architecture/API.md) e [suporte de plataforma](../architecture/PLATFORM_SUPPORT.md).
