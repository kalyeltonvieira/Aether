# Módulos e responsabilidades

| Responsabilidade | Módulos canônicos |
|---|---|
| Conhecimento | `aether.core.knowledge.store`: Entity, Fact, Provenance, KnowledgeStore |
| Inferência/reasoning | `aether.reasoning.inference`, `backward`, `hybrid`, `incremental`, `reasoner`, `controller`, `dependencies`, `consistency` |
| Grafos | `aether.graph.dynamic`, `engine`, `components`, `incremental_components`, `parallel`, `indexing.rust_knowledge` |
| Memória/políticas | `aether.memory.cache`, `adaptive_controller`, `adaptive_storage`, `patterns` |
| Temporal | `aether.temporal.events`, `checkpoints` |
| Native | `aether.native.bindings` e `aether.native/rust/aether_native.rs` |
| Adapters | `aether.adapters.snap_semantic` |
| Métricas de ferramenta | `aether.metrics` (portabilidade de medições, não política do grafo) |

Os módulos flat antigos em `src/aether_*.py` são aliases de transição para manter imports consumidores; o código de domínio existe apenas no caminho canônico.
