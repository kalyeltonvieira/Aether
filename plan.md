# Plano de evolução do AETHER

## Escopo e princípios

Fonte de requisitos: `/home/ubuntu/upload/pasted_content.txt`, o plano integral fornecido pelo usuário. A implementação continua na branch `evolution/aether-platform`, sem alterar `main`, `phase7`, `phase7new` ou `phase8`, sem merge automático e com commits separados por etapa. As etapas A–D estão registradas nos commits `9a8e99f`, `7c8d7e7`, `abd6b4b` e `a153a0e`; a etapa E conclui a API e AETHER Studio.

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

## Etapas

A–D: melhorias já commitadas e documentadas, com a evidência e limitações registradas em `docs/architecture/`. A etapa D ainda recebe uma atualização curta de seleção sensível à pressão de memória, depois de medir e testar a implementação.

E: implementar primeiro o contrato e estado da API, em seguida páginas e componentes, ligar cada tela a endpoints reais, implementar o fluxo CRUD → inferência → prova → remoção/recomputação → histórico, conectar WebSocket e persistência, finalizar docs/scripts multiplataforma e validar o conjunto. Nada será publicado em serviço público; a branch GitHub autorizada só será publicada quando todas as etapas forem verificadas.

## Condições de suporte e limites

Python ≥3.10 e Rust 1.99.1 seguem o projeto. A sessão atual comprova diretamente Linux ARM64; Windows/Linux x86_64 precisam de execução real em runners correspondentes ou serão marcados pendentes, nunca inferidos. O modo Studio é local/desenvolvimento com autenticação. Deploy público, contas multiusuário e banco gerenciado ficam fora desta entrega. Sessões, autorização, CSRF e login serão testados, sem alegar auditoria de produção.
