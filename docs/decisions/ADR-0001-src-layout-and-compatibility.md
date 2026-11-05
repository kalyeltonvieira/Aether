# ADR-0001: pacote `src/` e compatibilidade temporária

**Status:** adotada para a branch `architecture/repository-reorganization`
**Data:** 2026-11-05

## Contexto

O projeto distribuía módulos top-level com imports planos, apesar de agrupar domínio, testes e harnesses na raiz. O código Rust era localizado ao lado do wrapper e o manifesto SNAP era descoberto relativamente ao diretório dos scripts. A migração estrutural exige imports instaláveis fora do checkout sem quebrar imediatamente consumidores dos nomes antigos.

## Decisão

Implementar o pacote regular `src/aether` por responsabilidade; tratar benchmarks como módulos em `benchmarks/`; organizar testes em categorias; mover documentos históricos por `git mv`; deixar datasets grandes externos e empacotar somente o manifesto; colocar a fonte FFI sob `aether.native/rust/` como recurso do pacote. Imports flat de domínio permanecem por uma janela transitória como módulos que apenas reexportam os objetos canônicos. Entrypoints históricos de benchmark também encaminham ao módulo já movido, sem segunda implementação.

O código nativo compila para um cache gravável do usuário ou caminho explicitamente configurado por `AETHER_NATIVE_CACHE_DIR`; não grava em `site-packages`. Métricas não disponíveis são `None`. Os resultados históricos são preservados sem regeneração.

## Consequências

A API modular instalada e a execução fora do checkout tornam-se possíveis. A camada de aliases precisa ser removida somente após período de depreciação documentado. A portabilidade só pode ser declarada após os jobs reais por sistema. Linux ARM64 permanece pendente até runner disponível. A CI deve instalar/buildar o pacote e executar a suíte completa, incluindo FFI e portabilidade.
