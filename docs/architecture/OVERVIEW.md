# Visão geral da arquitetura AETHER

AETHER é um protótipo experimental com dois domínios relacionados, porém distintos: grafos mutáveis e raciocínio simbólico sobre fatos relacionais estruturados. A organização por `src/aether` separa implementação instalável de harnesses históricos, testes, documentação, dados/manifestos e resultados.

```text
src/aether/              API instalável e implementação Python
  core/knowledge/        entidades, fatos, evidências, snapshots e KnowledgeStore
  reasoning/             forward, backward, híbrido, incremental e controller
  memory/                cache, padrões, memória operacional SQLite e políticas
  graph/                 DynamicGraph, consultas, componentes e índice Rust
  temporal/              Event Engine SQLite, replay e checkpoints; logs de grafo em memória
  native/                wrapper ctypes e fonte Rust FFI
  adapters/              projeção auditável dos dados SNAP
  interfaces/api/        FastAPI opcional, sessão, autorização, REST e WebSocket
frontend/                AETHER Studio React/TypeScript/Vite, independente do núcleo
scripts/                 launcher local portável e entrypoints shell/PowerShell
benchmarks/              harnesses e plots por fase
  _paths.py              helpers comuns de descoberta do checkout/manifesto
tests/                   unit, integration, regression, concurrency, portability
datasets/manifests/      manifesto versionado; datasets grandes continuam externos
results/                 evidências históricas preservadas por fase
docs/                    arquitetura, fases, auditorias e desenvolvimento
```

O conhecimento tem snapshots atômicos com checksum e histórico de alterações retido por limite configurável. A `AdaptiveMemory` é distinta: armazena bytes operacionais e usa SQLite no cold tier; frequência observada não cria fatos semânticos. Consulte [raciocínio](REASONING.md) e [memória/persistência](MEMORY.md) para os contratos e limitações.

A árvore efetiva pode incluir shims top-level de compatibilidade durante a transição; eles apenas reexportam os módulos `aether.*` ou encaminham para o benchmark canônico e não contêm cópias de implementação.

## Fronteiras e dependências

O núcleo Python é importável sem compilar Rust. O backend nativo é opcional, compilado para o SO/arquitetura corrente quando solicitado e validado por ABI. Os benchmarks são ferramentas de pesquisa, não runtime. Resultados históricos são imutáveis e não são regenerados por CI. Dados SNAP não são empacotados; somente o manifesto e as regras de proveniência são versionados.

A API/Studio são camadas opcionais: instale o extra Python `api` e dependências do cliente apenas quando for operar a interface. O motor não depende de React/FastAPI. A API valida mutações e consultas, controla sessão/papéis/CSRF e projeta métricas/filas/provas reais; o cliente nunca substitui o núcleo por respostas simuladas. Detalhes de composição, persistência e limites de worker estão em [PLATFORM](PLATFORM.md), o contrato público em [API](API.md) e a operação em [WEB_STUDIO](../development/WEB_STUDIO.md).
