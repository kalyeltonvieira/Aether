# Relatório de evolução — AETHER

## Escopo e estado

As fases A–E estão implementadas em commits separados na branch `evolution/aether-platform`. A branch foi publicada no remoto autorizado. Na auditoria final, o GitHub já registrava o PR [#11](https://github.com/kalyeltonvieira/Aether/pull/11) dessa branch como mesclado em `main` pela conta `kalyeltonvieira` às 18:56:53 (-03), merge commit `0fd08c016e36779d61f0a140b0b8ca517e9c298d` (pais `479ab86` e `80b8f83`). Os comandos desta execução não iniciaram esse merge; nenhum revert será feito. Esta continuação publicará somente na branch de evolução. Os commits de implementação E `1939100` e de correção Windows `80b8f83` estão no remoto. A CI completa da correção está verde: workflow [42114719761](https://github.com/kalyeltonvieira/Aether/actions/runs/42114719761), 13/13 jobs aprovados.

O Studio separa o núcleo AETHER, a API FastAPI e o cliente React/TypeScript/Vite. A UI usa REST e WebSocket; o servidor valida os padrões como dados estruturados, compõe `KnowledgeStore`, `KnowledgeReasoner`, `AdaptiveMemory` e `EventEngine` reais, e não expõe execução Python arbitrária. Operações nativas só são declaradas disponíveis quando a biblioteca é realmente encontrada/carregada; métricas não instrumentadas permanecem `null`. O frontend separa os módulos por rota, e o build atual não emite o alerta anterior de chunk maior que 500 kB.

## Progresso por fase

## Progresso por fase

| Fase | Estado | Evidência principal |
|---|---|---|
| A — conhecimento e raciocínio | Concluída | Commit `9a8e99f`: evidência/proveniência alternativas, identidade escalar tipada, provas e paginação estável de consultas abertas; API antiga e aliases preservados. |
| B — memória e aprendizado incremental | Concluída | Commits `7c8d7e7` e `1c25fa2`: SQLite/cold tier, snapshots tipados verificáveis e checksum, histórico limitado, limites globais de padrões, recuperação e migração testadas. |
| C — eventos | Concluída | Commit `abd6b4b`: Event Engine SQLite ordenado, deduplicação, backpressure, retry/replay/checkpoint; integração com o Reasoner incremental e semântica documentada at-least-once. |
| D — eficiência | Concluída | Commits `a153a0e` e `d453b2f`: planner seletivo mensurável, controller com memória observada, benchmarks independentes e decisão conservadora de não promover estratégia adaptativa que perdeu das fixas. |
| E — API, segurança e AETHER Studio | Concluída; CI multiplataforma verde | Commits `1939100` e `80b8f83`: FastAPI + React/Vite, autenticação/token independente, contrato Manus OAuth, OpenAPI, nove rotas, WebSocket, persistência, CRUD, grafo, reasoning/proofs, memória, eventos, métricas, settings, launchers Windows/Linux e capturas reais. A CI final passou em 13/13 jobs; ver limites de validação abaixo. |

## Validação executada neste checkout

Ambiente local desta sessão: Linux `aarch64` (`Linux-6.18.38+-aarch64-with-glibc2.39`), CPython 3.12.3, Rust 1.99.1, Node v22.23.4 e pnpm 11.25.0. A FFI e o core foram exercitados nessa arquitetura; não se extrapola o resultado para outros SOs/CPUs.

- Python `unittest`: 220 testes aprovados, zero falhas.
- Python `pytest`: 220 aprovados; uma advertência de depreciação emitida por `starlette.testclient` e `httpx`, não uma falha de teste.
- Frontend: `tsc -b` aprovado, seis arquivos/15 testes Vitest aprovados e build de produção aprovado. As páginas são importadas sob demanda.
- Playwright/Chromium: 2/2 testes E2E aprovados no checkout final. Um executa criação de entidades/fato/regra, consulta, conclusão e prova navegável, remoção do suporte, confirmação de invalidação e histórico; o outro percorre as nove rotas autenticadas, valida ausência de alertas/erros de runtime e testa menu a 390 px. WebSocket real aceitou conexões no teste.
- Empacotamento Python: wheel e sdist construídos; pacote API e recursos Rust presentes no wheel verificado.
- Build e manifesto de rotas: JSON válido, nove rotas registradas.
- CI GitHub final, run `42114719761`, commit `80b8f83`: 13/13 jobs aprovados — Python 3.10/3.12/3.13 em Ubuntu, macOS e Windows; Studio em Ubuntu e Windows; fluxo browser E2E em Ubuntu e Windows. Isso resolveu as falhas de handles SQLite e `fsync` reportadas na primeira CI.

## Benchmarks

Os harnesses preservam resultados anteriores, usam oráculo independente e registram ambiente/hashes. Consulte `results/evolution/` e os documentos especializados; não usar estas medições como SLO ou comparação cross-platform.

- Raciocínio/join: holdout `1,626×` na família seletiva e empate na família balanceada; planner continua opt-in.
- Controller: 2.400 consultas em dez famílias, equivalência com oráculo e zero divergências; o custo adaptativo perdeu de estratégia fixa em nove famílias, por isso não é padrão. Ver `docs/architecture/EFFICIENCY.md`.
- Rust/grafos: benchmark de ciclo completo com conversão/build/FFI/atualização/recuperação e oráculo independente; holdout mediu `3,694×` em grafo esparso e `1,561×` em grafo denso. Não é alegação sobre inferência simbólica.
- Memória/eventos/snapshots: 30 seeds por família para custo de manutenção/recuperação e critérios de integridade. Ver `docs/architecture/OPERATIONAL_BENCHMARKS.md`.
- API/Studio: medição pós-correções Windows, 20 seeds de calibração + 10 holdout, 30/30 oráculos corretos; hashes das 16 fontes API conferidos com o checkout. No Linux ARM64/CPython 3.12.3, mediana do pipeline completo: 457,3 ms na calibração e 466,7 ms no holdout; P95 observado: 501,8 ms e 499,1 ms; CPU mediana: 420,4 ms e 431,1 ms; reinício mediano: 48,9 ms e 50,0 ms. O RSS de pico no artefato é uma medida global do processo. Ver `docs/architecture/API_BENCHMARK.md` e `results/evolution/phase9_api_portability_final.json`.

Não foi medida energia. Throughput de janela e RSS high-water não são limites garantidos de capacidade.

## Capturas reais

`docs/development/STUDIO_SCREENSHOTS.md` incorpora capturas de Chromium da aplicação/API autenticadas em store temporário. Knowledge Graph, Reasoning Console e Proof Explorer foram fotografados enquanto as entidades, relação e prova do E2E existiam; depois, o teste remove o suporte. A tela Dashboard registra honestamente o estado `incomplete` pós-remoção. As imagens não usam dados de produção.

## Limites de validação e implantação

1. **Windows cliente:** a CI passou em `windows-latest` (runner x64), incluindo Python 3.10/3.12/3.13, frontend e E2E integrado. Não foi feita instalação manual em máquinas/VMs Windows 10 ou 11 desktop; portanto, a evidência comprova o runner Windows, mas não uma validação visual/manual específica de cada edição cliente.
2. **OAuth real:** validado. `auth/info` informa disponibilidade, `login-url` retorna `https://manus.im/app-auth` com parâmetros oficiais, e o cookie OAuth state no Preview é `Secure; HttpOnly; SameSite=None`. Depois do login Manus real e do callback, o navegador retornou à página `/reasoning` com uma sessão verificada no papel `reader`; não houve mutação de dados. O protocolo de troca `ExchangeToken`/`GetUserInfo` também tem teste com fixture HTTP. Para escrita, um administrador precisa adicionar o openId do operador a `AETHER_OPERATOR_OPEN_IDS` no servidor; autenticar identidade não concede escrita automaticamente.
3. **Preview vs produção:** servidor/API local de Preview está ativo, mas a aplicação não foi publicada publicamente. A entrega autorizada foi a branch GitHub; branch e Preview não são publicação de produção.
4. **Aviso não bloqueante:** `pytest`/benchmark ainda emite depreciação de `starlette.testclient` com `httpx`; os testes passam, mas a compatibilidade futura deve ser acompanhada.

## Como executar

No checkout da branch, instale `python -m pip install -e ".[api]"` e `pnpm --dir frontend install --frozen-lockfile`. Inicie ambos com `python scripts/run_studio.py` (Windows PowerShell: `scripts/dev-studio.ps1`; Linux: `bash scripts/dev-studio.sh`) e abra `http://localhost:3000`. A API usa o modo token em instalação independente local e Manus OAuth no ambiente gerenciado; ela não abre acesso de operador a uma sessão OAuth apenas por autenticar a identidade. Veja `docs/development/WEB_STUDIO.md`, `docs/development/SETUP_WINDOWS.md` e `docs/development/SETUP_LINUX.md`.
