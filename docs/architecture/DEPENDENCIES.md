# Dependências arquiteturais

```text
core.knowledge <- reasoning.*
core.knowledge <- adapters.snap_semantic
core.knowledge <- graph.indexing.rust_knowledge <- native.bindings
core + graph <- temporal.*
core/graph/reasoning <- memory policies and controllers
benchmarks -> public package APIs; tests -> public package APIs + benchmark harnesses
```

`aether.native.bindings` não é importado/compilado pelo núcleo ao importar `aether`; operações nativas ocorrem sob demanda. Os benchmarks não são dependência de runtime. A suíte testa essa separação via import smoke e wheel limpo. Shims flat importam somente para frente aos módulos canônicos, sem dependência reversa dos módulos `aether.*` para os shims.
