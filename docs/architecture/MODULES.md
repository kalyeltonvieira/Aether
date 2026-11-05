# Módulos e responsabilidades

| Responsabilidade | Módulos canônicos |
|---|---|
| Conhecimento | `aether.core.knowledge.store`: Entity, Fact, FactEvidence, KnowledgeChange, Provenance, KnowledgeStore; `aether.core.knowledge.persistence`: snapshots `save_store`/`load_store` |
| Inferência/reasoning | `aether.reasoning.inference`, `backward`, `hybrid`, `incremental`, `reasoner`, `controller`, `dependencies`, `consistency` |
| Grafos | `aether.graph.dynamic`, `engine`, `components`, `incremental_components`, `parallel`, `indexing.rust_knowledge` |
| Memória/políticas | `aether.memory.cache`, `adaptive_controller`, `adaptive_storage` (SQLite cold tier), `patterns` |
| Temporal | `aether.temporal.engine` (fila/log SQLite, retries, replay e checkpoints), `knowledge` (handlers no KnowledgeReasoner), `events`, `checkpoints` |
| Native | `aether.native.bindings` e `aether.native/rust/aether_native.rs` |
| Adapters | `aether.adapters.snap_semantic` |
| Métricas de ferramenta | `aether.metrics` (portabilidade de medições, não política do grafo) |
| API REST/WebSocket | `aether.interfaces.api`: app, schemas, routes, services, dependencies e websocket; compõe núcleo, validação e sessão |
| Studio independente | `frontend/`: React/TypeScript/Vite, páginas, componentes, serviços de API e hooks de atualização |
| Operação local | `scripts/run_studio.py` e entrypoints shell/PowerShell; inicia e encerra os processos locais |

Os módulos flat antigos em `src/aether_*.py` são aliases de transição para manter imports consumidores; o código de domínio existe apenas no caminho canônico.
