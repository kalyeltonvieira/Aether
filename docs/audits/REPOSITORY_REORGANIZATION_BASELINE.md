# Auditoria inicial — reorganização do repositório AETHER

**Data da auditoria:** 2026-11-05 16:18 BRT
**Base/branch fonte:** `main` = `a50b265d187041f0491fdfad2b7c92ddd691fefb`
**Branch de trabalho:** `architecture/repository-reorganization`, criada localmente a partir desse SHA.
**Estado inicial do working tree:** limpo. Nenhum arquivo da base foi editado antes desta auditoria.
**Branches protegidas verificadas:** `main`, `phase7`, `phase7new` e `phase8` existem e seus refs não serão alterados. O nome da branch de arquitetura não existia no remoto na auditoria.

## Inventário da base

O checkout contém 230 arquivos rastreados: 66 arquivos Python (65 na raiz e 1 em `archive/v1`), 2 fontes Rust na raiz, 23 módulos de teste `test_*.py`, 30 arquivos Python com nomes contendo `bench`, 17 documentos Markdown e 136 arquivos sob `results/`. Esses grupos se sobrepõem (testes e benchmarks são Python). A raiz concentra código de domínio, entrypoints de benchmark, testes, relatórios das fases e configuração de build; existe um diretório `archive/v1/` com código/resultados históricos.

Os 23 módulos Python de domínio na raiz incluem conhecimento, inferência, backward/hybrid, reasoner/controladores, memória/padrões, grafos/componentes/cache, temporal/checkpoints, integrações SNAP/Rust e paralelismo. Os 2 fontes Rust são `aether_native.rs` (biblioteca FFI carregada por `ctypes`) e `rust_dfs_kernel.rs` (kernel separado usado na avaliação de benchmark; não é a biblioteca FFI principal). Os 17 documentos ficam principalmente na raiz; os resultados históricos estão já subdivididos em `results/phase2` até `phase7new`, além de dois arquivos baseline na raiz de `results/`.

## Imports, build e contratos observados

- O pacote é atualmente uma coleção de módulos top-level. `pyproject.toml` declara um `py-modules` allowlist; os 23 módulos de runtime são importados por seus nomes planos (`aether_knowledge`, `aether_reasoner`, etc.).
- Testes, benchmarks, scripts e exemplos do README usam imports planos; diversos benchmarks importam outros benchmarks como helpers. Mover arquivos sem atualizar imports e entrypoints quebra execução e descoberta.
- `aether_native.py` localiza `aether_native.rs` ao lado de seu arquivo-fonte e compila com `rustc`. `setup.py` copia esse `.rs` para junto do módulo no wheel; `MANIFEST.in` cobre o source distribution. A nova localização precisará atualizar loader, build e distribuição do recurso Rust sem mudar a ABI.
- O benchmark Fase 4 produz nome de biblioteca `.so` fixo em um caminho, apesar de o wrapper suportar `.dll`, `.so` e `.dylib`.
- `phase2_bench.py`, `phase3_bench.py`, `phase4_bench.py`, `aether_bench.py` e `archive/v1/aether_bench.py` importam `resource` no topo. A ausência desse módulo no Windows impede importação/discovery de testes que dependem dos benchmarks.
- Há leituras de `/proc` em medição de memória/hardware. Parte das medições degrada para 0/unknown; as unidades e o valor de 0 devem ser documentados como medida indisponível, não como uso real zero.
- O uso de subprocess nos workloads passa argumentos como lista; a concorrência do módulo `aether_parallel.py` é baseada em threads, sem dependência observada de `fork`/multiprocessing.
- Dados SNAP completos não estão no checkout: os arquivos são externos/ignorados. Os testes semânticos usam fixtures; reprodução integral exige baixar os dados e conferir hashes/proveniência.

## Linha de base executada antes da migração

### Linux local

- Python `3.12.3`; Rust `1.99.1` disponível.
- Comando: `python3 -m unittest discover -v` na raiz do checkout limpo.
- Resultado observado: **127 testes executados, 127 passaram, 0 falharam, 0 ignorados**, em 3,310 s (`OK`). Essa contagem corresponde a esta execução na base acima e prevalece para este registro; ela é distinta de contagens de outros snapshots/run environments históricos.
- Nenhum benchmark completo foi reexecutado para estabelecer uma nova performance de referência; resultados rastreados foram inventariados e devem permanecer byte a byte preservados.

### CI remota de `main`

- Run [42073547517](https://github.com/kalyeltonvieira/Aether/actions/runs/42073547517), SHA `a50b265d187041f0491fdfad2b7c92ddd691fefb`, conclusão global **failure**.
- Linux: Python 3.10, 3.12 e 3.13 passaram (3/3). macOS: Python 3.10, 3.12 e 3.13 passaram (3/3). Windows: Python 3.10, 3.12 e 3.13 falharam (0/3).
- Em cada job Windows, o log registra 112 testes e 5 erros: importação de benchmarks/testes que dependem de `resource`, além de falha de permissão ao reabrir/remover o temporário `tmp*.txt` no teste de hash SNAP. A matriz atual não cobre Linux ARM64.
- Run anterior na mesma base, [42073462889](https://github.com/kalyeltonvieira/Aether/actions/runs/42073462889), também falhou. Não declaramos Windows validado antes da migração.

## Riscos e controles de preservação

1. Compatibilidade de imports: adicionar pacote `src/aether`, atualizar todos os imports internos/testes/benchmarks/docs e manter shims top-level finos (sem segunda implementação) quando necessário para compatibilidade antiga.
2. Preservar scripts/benchmarks históricos com entrypoints reproduzíveis e outputs de resultados imutáveis; novos smoke outputs devem usar diretórios novos.
3. Preservar testes/oráculos, nomes e força das assertions; reorganizar os testes como unidades, integração e portabilidade sem perder descoberta `unittest`.
4. Incluir fontes Rust no sdist/wheel e testar instalação limpa/editável e compilação/load real por OS; não reutilizar binário entre SO/arquiteturas.
5. Windows e Linux prioritários. Linux ARM64 somente será chamado de testado se um runner/dispositivo ARM real ficar disponível; ausência de runner será reportada.
6. Atualizar links, comandos e documentação, mantendo relatórios antigos identificados como registros históricos e sem alterar resultados arquivados.

## Branches observadas na auditoria

Remotas presentes: `main`, `phase5`, `phase6`, `phase6new`, `phase7`, `phase7new`, `phase8` e `manus/fix-aether-reasoner-packaging-ci`. Apenas a nova branch exclusiva `architecture/repository-reorganization` receberá commits desta tarefa. Sem merge automático e sem reescrita de histórico.
