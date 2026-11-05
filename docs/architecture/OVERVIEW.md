# Visão geral da arquitetura AETHER

AETHER é um protótipo experimental com dois domínios relacionados, porém distintos: grafos mutáveis e raciocínio simbólico sobre fatos relacionais estruturados. A organização por `src/aether` separa implementação instalável de harnesses históricos, testes, documentação, dados/manifestos e resultados.

```text
src/aether/              API instalável e implementação Python
  core/knowledge/        entidades, fatos, proveniência e KnowledgeStore
  reasoning/             forward, backward, híbrido, incremental e controller
  memory/                cache, políticas, padrões e memória adaptativa
  graph/                 DynamicGraph, consultas, componentes e índice Rust
  temporal/              eventos e checkpoints
  native/                wrapper ctypes e fonte Rust FFI
  adapters/              projeção auditável dos dados SNAP
benchmarks/              harnesses e plots por fase
  _paths.py              helpers comuns de descoberta do checkout/manifesto
tests/                   unit, integration, regression, concurrency, portability
datasets/manifests/      manifesto versionado; datasets grandes continuam externos
results/                 evidências históricas preservadas por fase
docs/                    arquitetura, fases, auditorias e desenvolvimento
```

A árvore efetiva pode incluir shims top-level de compatibilidade durante a transição; eles apenas reexportam os módulos `aether.*` ou encaminham para o benchmark canônico e não contêm cópias de implementação.

## Fronteiras e dependências

O núcleo Python é importável sem compilar Rust. O backend nativo é opcional, compilado para o SO/arquitetura corrente quando solicitado e validado por ABI. Os benchmarks são ferramentas de pesquisa, não runtime. Resultados históricos são imutáveis e não são regenerados por CI. Dados SNAP não são empacotados; somente o manifesto e as regras de proveniência são versionados.
