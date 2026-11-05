# Plano de evolução do AETHER

## Estado atual e roadmap
O Studio está integrado em `main` no commit `0fd08c016e36779d61f0a140b0b8ca517e9c298d`; CI para esse SHA passou 13/13 jobs ([run 42117194839](https://github.com/kalyeltonvieira/Aether/actions/runs/42117194839)). A branch `fix/stage1-reliability` também passou 13/13 jobs ([run 42125306398](https://github.com/kalyeltonvieira/Aether/actions/runs/42125306398)); sua revisão/merge ainda está pendente, então a Etapa 1 não está concluída.

1. **Consolidação e confiabilidade — aguardando integração:** os três achados foram corrigidos em `fix/stage1-reliability`: expiração Preview limitada ao JWT, persistência desligada em todos os stores de domínio no startup e OAuth state reservado antes de I/O. Validação local aprovada (unittest 207/6 skips, pytest 202/21 skips por ausência de `rustc`; frontend typecheck, 16 testes, build; wheel inclui `benchmarks.phase9`) e CI remota 13/13; falta revisão/merge.
2. **Núcleo cognitivo — primeira fatia implementada localmente:** `feat/contextual-evidence-v1` introduz contexto declarado por evidência e filtro antes da inferência, com compatibilidade de snapshot v1. A suíte local completa passou (unittest 207/6 skips; pytest 208/21 skips sem toolchain Rust; frontend typecheck, 19 testes, build e wheel); CI/revisão/merge dessa branch pendentes. Isto é seleção contextual inicial, não memória episódica, aprendizado/revisão, resolução de conflitos nem detector de insuficiência. Ver [contrato de contexto por evidência](docs/architecture/CONTEXTUAL_EVIDENCE.md).
3. **Autonomia e eficiência medida:** benchmarks delimitados; controller adaptativo perdeu para fixo em 9/10 famílias e não foi promovido; energia não medida.
4. **Integrações — não implementada:** LLM, linguagem natural, documentos, multimodalidade, ferramentas e agentes; LLM não é fonte de verdade.

## Contexto histórico e princípios
Os blocos e checklists A–E adiante são snapshots preservados, não o roadmap corrente. A implementação e o estado do Studio descritos neles são registros históricos.

O motor permanece independente do frontend: a camada HTTP integra as APIs públicas de `KnowledgeStore`, inferência, memória, eventos e métricas; React não importa módulos Python. Valores de status, contagens e gráficos vêm do processo real. Métricas não disponíveis serão `null`/“indisponível”, nunca números de demonstração. Sem execução arbitrária de Python, sem CORS `*` e sem publicação pública nesta etapa. Como o Preview é acessível pela rede, autenticação e proteção de sessão entram desde o início: Manus OAuth gerenciado, validação JWT/projeto/expiração, operadores por allowlist e token de operador somente em instalação independente explicitamente configurada. Cookies são HttpOnly; mutações exigem CSRF; origens WebSocket/CORS são restritas. Os comandos locais prendem a API ao loopback. Persistência usa snapshots verificáveis e SQLite; não habilitar banco ou Redis gerenciados.

## Arquitetura escolhida

- **API:** FastAPI/Pydantic em `src/aether/interfaces/api/`, organizado em `app.py`, `routes/`, `schemas/`, `services/`, `dependencies/` e `websocket/`. O app compõe o núcleo existente, persiste snapshots depois de mutações bem-sucedidas e valida limites de tamanho, paginação, IDs e configurações. A API fornece health/status, entidades, fatos, grafo, histórico, regras/consultas, provas, memória, eventos, métricas e configuração. O WebSocket transmite notificações de eventos/atualizações efetivamente processados; falha de conexão não altera a semântica do Event Engine.
- **Cliente:** React + TypeScript + Vite em `frontend/`, com `src/app/`, `components/`, `layouts/`, `pages/`, `features/{dashboard,knowledge,reasoning,memory,events,monitoring}/`, `services/`, `hooks/`, `types/` e `styles/`. O proxy Vite encaminha `/api` e `/ws` ao servidor local FastAPI.
- **Estado:** uma instância por processo de Studio; o KnowledgeStore é restaurado por snapshot; regras e limites têm persistência/configuração versionada própria; eventos usam o log SQLite existente. Escritas da UI passam pela API e retornam os registros canônicos e seu estado de completude.
- **Visual:** direção solicitada — tema escuro, grafite, azul/ciano, identidade própria e responsiva. Princípios: observabilidade sem números fictícios; prova rastreável; hierarquia limpa; densidade legível. Layout com navegação lateral, barra de estado da API/núcleo, área principal de trabalho e painel contextual. Grafos, logs e consultas usam superfícies grafite; ciano identifica foco/conexões, azul ações e cores semânticas para estados. Elementos assinatura: marca de nós conectados e linhas/arestas ciano; animação discreta e `prefers-reduced-motion`. Tipografia sans legível com monoespaçada em consultas/IDs/medidas. Marca: “AETHER Studio — inspecione o que o motor sabe e cada prova que o sustenta”; personalidade rigorosa, clara e sóbria. Não usar ilustrações decorativas em um dashboard interno.

## Áreas funcionais

Dashboard com status real de core/API/Rust, memória, CPU disponível, consultas, eventos, latência, atividade, alertas/erros; Knowledge Explorer para entidades/fatos/proveniência/histórico e CRUD validado; grafo interativo com zoom, pan, seleção, filtros e expansão de vizinhança via API; Reasoning Console para padrões relacionais, estratégia, limites, duração, bindings e completude; Proof Explorer para regra, suportes, alternativas, profundidade, proveniência e dependências; Memory Center para hot/warm/cold, orçamento, acesso, cache, evicções, recuperação e persistência; Event Monitor para fila, estados, falhas, tentativas, histórico e atualizações em tempo real; Performance Monitor para CPU/memória/latência/throughput/operações Rust/consultas/eventos e comparação de estratégias; Settings para orçamento/limites/estratégia/componentes/persistência com validação pela API.

## Estrutura pretendida

```text
src/aether/interfaces/api/
  app.py
  routes/ schemas/ services/ dependencies/ websocket/
frontend/
  src/app/ components/ layouts/ pages/
  src/features/{dashboard,knowledge,reasoning,memory,events,monitoring}/
  src/services/ hooks/ types/ styles/
  public/ package.json vite.config.ts
scripts/
  dev-api.sh dev-api.ps1
  dev-studio.sh dev-studio.ps1
  dev-all.sh dev-all.ps1
 tests/unit/api/ tests/integration/api/
 frontend/src/**/*.test.tsx
 docs/architecture/{API,PLATFORM}.md
 docs/development/{SETUP_WINDOWS,SETUP_LINUX,WEB_STUDIO}.md
```

Arquivos Python novos serão incluídos nos pacotes/setuptools e CI existentes; dependências web serão fixadas no lockfile. A documentação existente de Windows/Linux será atualizada, não substituída por caminhos absolutos. O frontend inclui manifest de rotas e testes de componentes; o backend terá contrato OpenAPI, validação e testes que exercitam o núcleo real.

## Snapshot histórico: etapas A–E
O plano anterior organizava trabalho em fases A–E para conhecimento, memória/eventos/eficiência e Studio/API. Mantém-se para proveniência; não significa conclusão do roadmap de quatro etapas acima.
## Condições de suporte e limites

Python ≥3.10 e Rust 1.99.1 seguem o projeto. A sessão atual comprova diretamente Linux ARM64; Windows/Linux x86_64 precisam de execução real em runners correspondentes ou serão marcados pendentes, nunca inferidos. O modo Studio é local/desenvolvimento com autenticação. Deploy público, contas multiusuário e banco gerenciado ficam fora desta entrega. Sessões, autorização, CSRF e login serão testados, sem alegar auditoria de produção.
