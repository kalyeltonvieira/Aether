# Entregas AETHER — critérios e estado

Este roadmap substitui a organização antiga em etapas A–E. Os checklists abaixo são snapshots históricos de critérios/evidências, não uma declaração de conclusão do roadmap atual.

## [~] Etapa 1 — consolidação e confiabilidade (em andamento)
O Studio está integrado em `main` no commit `0fd08c016e36779d61f0a140b0b8ca517e9c298d`; CI desse SHA passou 13/13 jobs ([run 42117194839](https://github.com/kalyeltonvieira/Aether/actions/runs/42117194839)). A branch `fix/stage1-reliability` corrige os três achados: sessão Preview limitada ao `exp` do JWT, stores de domínio efetivamente efêmeros no modo sem persistência e reserva de OAuth state antes de I/O. A validação local passou e a CI remota passou 13/13 jobs ([run 42125306398](https://github.com/kalyeltonvieira/Aether/actions/runs/42125306398)); falta revisão/merge, portanto a etapa segue aberta.

## [~] Etapa 2 — núcleo cognitivo (parcial)
`feat/contextual-evidence-v1` introduziu contexto por evidência. A branch local ainda não enviada `feat/evidence-review-v1` acrescenta retirada individual de evidência, invalidação de provas/conclusões dependentes e ledger persistente de decisões humanas; as revisões ficam obsoletas monotonicamente quando suas evidências mudam. Validação local: unittest 218/6 skips e pytest 213/21 skips devido à ausência do toolchain Rust; CI da branch nova pendente. API/Studio ainda não expõe essas operações. Aprendizado de estruturas, revisão automática, raciocínio contextual multi-etapas e detecção automática de insuficiência seguem pendentes. Contratos: [CONTEXTUAL_EVIDENCE.md](docs/architecture/CONTEXTUAL_EVIDENCE.md) e [EVIDENCE_REVIEW.md](docs/architecture/EVIDENCE_REVIEW.md).

## [~] Etapa 3 — autonomia e eficiência medida
Há benchmarks delimitados. O controller adaptativo perdeu para estratégia fixa em 9/10 famílias e não foi promovido; energia não foi medida.

## [—] Etapa 4 — integrações (fora do escopo ativo)
AETHER permanece um núcleo simbólico/relacional independente. Não há integração LLM, NLP ou agentes no escopo atual. Conectores determinísticos de fontes/ferramentas só devem ser planejados diante de um caso de uso concreto e com proveniência verificável.

## Snapshot histórico de fases anteriores
Cada item mantém os critérios do brief original junto do resultado correspondente. Status não presume testes em sistemas que não foram executados.

## [x] Etapa A — conhecimento e raciocínio robusto

- A representação implementa ou aperfeiçoa entidades, fatos, relações, propriedades, tipos de dados, proveniência, confiança declarada, histórico de alterações, identificação estável e indexação eficiente; valores de tipos diferentes não colidem indevidamente; fatos explícitos permanecem distintos de derivados.
- O raciocínio abrange forward chaining, backward chaining, raciocínio híbrido, unificação de variáveis, consultas abertas, múltiplas soluções, múltiplas provas por conclusão, explicações e limites computacionais. Remover uma prova não invalida uma conclusão que continue sustentada por outra prova válida.
- A consistência identifica contradições e incompatibilidades explicitamente declaradas; diferencia desconhecido/contradito; verifica dependências, invalida localmente e recompõe com segurança; não resolve conflitos silenciosamente.
- Consultas relacionais como `(?x, sent_email_to, ?y)` retornam soluções válidas, bindings, provas e explicações; consultas grandes têm paginação/limites; oráculos independentes/recomposição são usados nos workloads; resultados incompletos são identificados.
- Evidência: `9a8e99f`; suíte completa da branch registrada na validação da etapa D.

## [x] Etapa B — memória e aprendizado incremental

- Há hot/warm/cold memory, limites configuráveis, deduplicação, recuperação, persistência, estatísticas de acesso, política de substituição e orçamento residente controlável.
- Aprendizado incremental registra frequência de consultas/chaves/tipos de operação, relações e transições curtas observadas, padrões recorrentes e custos históricos, com limites de armazenamento/atualização. Frequência não é compreensão, verdade ou relevância semântica.
- Histórico de eventos, consultas, estatísticas de acesso, conhecimento persistente e padrões computacionais permanecem conceitos separados; uma sequência frequente nunca vira automaticamente uma relação verdadeira.
- Estado pode ser salvo/recuperado com integridade, versão incompatível detectada e corrupção interrompida; limites e custo de manutenção/recuperação são demonstrados.
- Evidência: `7c8d7e7`; testes de recuperação após reinício, checksum e migração do journal legado.

## [x] Etapa C — processamento orientado a eventos

- Eventos têm ID, tipo, timestamp, origem, payload/proveniência JSON validável, ordem e estado; fila permite lote, backpressure, concorrência serializada, falha, retry, deduplicação e recuperação.
- Eventos inserem/removem fatos/entidades, propagam mudanças, invalidam dependentes e atualizam conclusões somente onde a estratégia incremental é segura; a equivalência com recomputação completa é exercitada.
- O contrato real não promete exactly-once: processamento é at-least-once, handler deve ser idempotente por ID; eventos duplicados, fora de ordem, interrupções, retries e concorrência são testados.
- Histórico oferece estado atual, versões anteriores, checkpoints verificados, replay, comparação e auditoria.
- Evidência: `abd6b4b`; Event Engine SQLite e teste de integração evento→Reasoner→provas→remoção→snapshot.

## [x] Etapa D — eficiência e otimização adaptativa

- O controller escolhe entre estratégias conforme tipo de consulta, tamanho do conhecimento, densidade, número de variáveis, histórico, memória disponível, custo estimado, latência observada e custo de manutenção. Estratégias fixas e adaptativas são comparadas com calibração e holdout.
- Otimizações avaliadas incluem índices compostos, cache, planejamento/ordenação de joins, redução de leituras, deduplicação, recuperação seletiva e lotes; só entram quando há evidência.
- Rust é avaliado em operações intensivas, estruturas compactas, lote, indexação, eventos e grafos; medir conversão, construção, atualização, execução, recuperação, memória e FFI, preservando equivalência Python/Rust. Paralelismo só entra quando há benefício real, avaliando isolamento e segurança.
- Registrar latência, mediana, P95 observado, memória, CPU, operações examinadas, throughput, custos de manutenção/decisão e energia somente se medida; não inventar métricas.
- Nenhuma estratégia adaptativa é promovida como padrão se perder consistentemente para uma estratégia fixa equivalente.
- Evidência: `a153a0e` e `d453b2f`; planner seletivo tem speedup de holdout 1,626× na família seletiva, mas empate no balanceado; a integração de pressão de memória foi testada e o holdout existente executou 2.400 consultas em dez famílias/30 seeds, zero divergências de oráculo e zero falhas em 240 paridades incrementais. O controller adaptativo perdeu contra estratégia fixa em nove famílias, portanto permanece opt-in. Benchmark de ciclo completo do Rust (build, FFI, updates, recuperação e oráculo) mediu speedup 3,694× em grafos esparsos e 1,561× em densos, holdout com 10 seeds/família. Benchmark de evidências está em `results/evolution/`; hardware, SO, versão e hashes acompanham os registros.

## [ ] Etapa E — AETHER Studio, API, segurança e operação

- **Arquitetura/visual:** API independente do core/frontend; React, TypeScript, Vite, FastAPI, REST, WebSocket, Python e Rust quando justificado; diretórios próprios de frontend e API; tema escuro padrão, grafite, azul/ciano, tipografia legível, gráficos organizados, animações discretas, navegação lateral, identidade AETHER e responsividade.
- **Dashboard:** exibir estados reais de core, API e Rust, memória, CPU, consultas, eventos, latência, atividade recente, alertas e erros; nenhum número fictício apresentado como real.
- **Knowledge Explorer/grafo:** entidades, pesquisa, fatos, relações, filtro de predicado, propriedades, proveniência, CRUD permitido e histórico; grafo com zoom, arrasto, seleção, relações filtráveis, expansão de vizinhanças e dados reais da API.
- **Reasoning/Proof Explorer:** consultas relacionais sem execução arbitrária, escolha de estratégias, resultados, bindings, tempo, completude/incompletude e erros; prova selecionada mostra conclusão, regra, suportes, alternativas, profundidade, proveniência e dependências; permitir navegar à evidência original.
- **Memory Center/Event Monitor/Performance Monitor/Settings:** mostrar hot/warm/cold, orçamento, acessos, cache, evicções, recuperação, persistência; fila/eventos processados/falhos/retries/filtro/histórico/realtime; gráficos CPU/memória/latência/throughput/consultas/eventos/Rust/comparação; períodos históricos; editar orçamento, limites, estratégia, componentes, persistência e execução somente com validação da API.
- **API/segurança:** endpoints organizados para status, conhecimento, entidades, fatos, consultas, inferência, explicações, memória, eventos, métricas e configuração; OpenAPI e validação; não expor código Python arbitrário ou internals sem validação; se rede-exposta, implementar autenticação, autorização e proteção de sessão; CORS restrito; segredos nunca no frontend.
- **Compatibilidade:** Windows 10/11 x86_64, Linux x86_64 e Linux ARM64 onde há runner; validar instalação Python/frontend, inicialização API/core, compilação Rust/FFI, comunicação, WebSocket, persistência, testes e encerramento; tratar DLL/SO/dylib e não usar paths absolutos; scripts PowerShell e shell; documentar os dois processos.
- **Validação:** testes de core, API, frontend e integração com dados/oráculo reais. E2E completo: iniciar AETHER, abrir Studio, criar entidades/fatos, consultar, derivar conclusão, ver prova, remover fato, verificar atualização das conclusões e consultar histórico; repetir fluxos críticos em Windows/Linux.
- **Docs/benchmarks:** criar/atualizar `docs/architecture/{OVERVIEW,PLATFORM,REASONING,EVENT_ENGINE,MEMORY,API}.md`, `docs/development/{SETUP_WINDOWS,SETUP_LINUX,WEB_STUDIO}.md`, guia de uso Studio e README; capturas reais quando disponíveis; benchmarks independentes para cinco áreas, ≥30 seeds/família quando aplicável, split calibração/holdout, custo completo, resultados em `results/evolution/`, ambiente/hardware/SO/versões/hashes, sem comparar ambientes incompatíveis.
- **Entrega Git:** publicar somente `evolution/aether-platform`, commits separados por fase, sem merge automático, sem modificar branches históricas. Ao final informar commits, arquivos, arquitetura, testes aprovados/falhos/ignorados, resultados por SO, benchmarks, estado API/UI, funcionalidades concluídas/pendentes e instruções.
- **Evidência até aqui (item permanece aberto):** Linux ARM64 local: `unittest` 220 OK; `pytest` 220 OK; frontend typecheck, 15 unit tests, build e Chromium E2E (2/2) OK; 10 capturas reais arquivadas; wheel/sdist construídos; benchmark API 30/30 oráculos em calibração/holdout. Login OAuth Manus real e callback no Preview foram concluídos; a sessão ficou `reader`, conforme política. Primeira CI executada: Python 3.10/3.12/3.13 em Ubuntu/macOS passou, Studio frontend Ubuntu/Windows passou e E2E Ubuntu passou; Windows Python e E2E detectaram `fsync` com handle somente leitura e handles SQLite não fechados em alguns testes. A correção local passou de novo em `unittest`/`pytest` 220 e E2E 2/2; a CI do follow-up ainda precisa passar. ARM64 foi validado apenas no host desta sessão; não declarar suporte Windows/Linux x86_64 antes do rerun remoto.

**Atualização corrente do snapshot:** a CI do commit base integrado a `main` passou 13/13 jobs ([run 42117194839](https://github.com/kalyeltonvieira/Aether/actions/runs/42117194839)). Os três reparos de confiabilidade estão implementados e validados localmente em `fix/stage1-reliability`; falta executar CI sobre essa branch e revisar/mesclar as mudanças.
