# AETHER — Phase 8: auditoria, correções e avaliação

**Data da execução:** 2026-11-05  
**Branch:** `phase8`  
**Base:** `a50b265d187041f0491fdfad2b7c92ddd691fefb` (`origin/main` no início)  
**Estado:** código e benchmark locais concluídos; validação remota da matriz GitHub Actions ainda pendente neste relatório. Não houve merge.

## 1. Auditoria inicial e integridade do Git

A auditoria inicial está preservada em [`PHASE8_AUDIT.md`](PHASE8_AUDIT.md). O checkout de trabalho foi criado limpo a partir da `main` atual; nenhuma alteração existente foi descartada. Os hashes observados no início foram `main` = `a50b265d187041f0491fdfad2b7c92ddd691fefb`, `phase7` = `233d193e0dac0167566610d161a4ca424509619e` e `phase7new` = `cd14200a86e8aa7e19c2cdf3880d81cdeadbfe35`. A branch remota `phase8` não existia. O PR anterior #7 já estava integrado à `main`.

Foram preservados o histórico e os relatórios anteriores. As correções de portabilidade tratam os erros Windows reproduzidos na auditoria-base: `resource` em imports de módulos ativos e reabertura de arquivo temporário ainda aberto. A importação `resource` foi removida também do benchmark arquivado quando verificado que era código morto; métricas de RSS usam o helper opcional e retornam `null` quando não disponíveis.

## 2. Decisões e alterações técnicas

| Área | Implementação | Validação |
|---|---|---|
| Identidade de escalares | Chaves tipadas distinguem `bool`, `int`, `float`, `str` e `None`; valores compostos não suportados são rejeitados. A semântica de igualdade/deduplicação Python anterior não pode ser mantida para `True`/`1` e `1`/`1.0`; IDs/chaves em snapshots persistidos devem ser reconstruídos ao migrar, e não reinterpretados silenciosamente. | `test_phase8_typed_scalars.py` e testes de índice/unificação. |
| Provas alternativas | Conclusão lógica é distinta de cada prova; cada prova conserva regra e suportes. Dependências reversas são mantidas por prova, então invalidar um suporte não remove uma conclusão que ainda tenha outra prova válida. | Testes com dois caminhos independentes e remoção de um e depois do último suporte. |
| Remoções | A invalidação local conserva as provas alternativas conhecidas. Como a completude pode depender de novas provas não observadas, o `KnowledgeReasoner` sinaliza recomputação pendente e impede ler conclusões antigas como atuais; `recompute()` refaz o fecho completo. | `test_phase7_reasoner.py`, `test_phase8_reasoning.py` e workload de remoção. |
| Consultas abertas | `InferenceEngine.query()` enumera bindings deduplicados, soluções, explicações, limites e estado de completude. O controlador expõe as soluções. Backward/hybrid rejeitam uma meta livre em vez de responder um booleano enganoso. | Variáveis repetidas/tipadas, encadeamentos, ciclos, ausência de resultado e limites. |
| Índice Rust | O índice guarda a versão do `KnowledgeStore`, recusa leitura obsoleta e troca o snapshot somente após refresh completo. A API distingue aresta direta de alcançabilidade transitiva. | Inserção, remoção, nova entidade, duplicate no-op e comparação Python/Rust. |
| Proveniência | Metadados tipados opcionais para URL, linha, registro, tipo de evidência e transformação; SNAP registra a linha de origem. Data/tempo e confiança permanecem ausentes quando a fonte não as fornece. Confiança declarada não é tratada como probabilidade calibrada. | `test_phase7_semantic.py` e `test_phase8_typed_scalars.py`. |
| Contradições | Status explícitos para conhecido, desconhecido, derivado, contradito e evidência insuficiente. Só regras de incompatibilidade declaradas criam conflito. Fontes conflitantes permanecem armazenadas; uma resolução fica registrada em separado. | Testes de valores tipados, regra declarada e resolução auditável. |
| Lifecycle de regras | Inserção, remoção, revisão e ativação/desativação têm IDs, revisão e versão/fingerprint. O reasoner invalida o resultado em cache e exige recomputação após mudança de regra. | `test_phase8_reasoning.py` e `test_phase7_controller.py`. |
| CI Windows | Coleta portátil de memória em `aether_metrics.py`; não há import top-level de `resource` no código ativo; o teste SNAP fecha o arquivo antes de reabri-lo. Testes funcionais não foram pulados. | A suíte local passou no Linux. A matriz remota Windows/macOS/Linux ainda não foi executada/confirmada no momento desta versão do relatório. |

### Compatibilidade e limites

A identidade de fato agora é tipada e deliberadamente não reproduz as colisões da igualdade padrão de Python. Os escalares suportados continuam limitados a `str`, `int`, `float`, `bool` e `None`; tuplas/estruturas compostas não passam a ser suportadas implicitamente. Para dados persistidos por versões antigas, exporte/recarregue os fatos para reconstruir IDs e índices. Não foi introduzida uma conversão automática de snapshots binários antigos.

O reasoner não presume que a invalidação incremental após remoção ou mudança de regras possa provar completude por si só. Nesses casos ele marca o estado como necessitando recomputação; isso é intencional para impedir resultados stale apresentados como completos.

## 3. Testes locais e build

Na execução local final: Linux x86_64, Python 3.12.3, CPU Intel Xeon @ 2.10 GHz e toolchain Rust 1.99.1. A suíte completa executada com `python3 -m unittest discover -v` registrou **153 testes aprovados, 0 falhos e 0 ignorados**. O resultado local não substitui a matriz multiplataforma.

Comandos de reprodução:

```bash
python3 -m unittest discover -v
python3 -m build
python3 -m benchmarks.phase8.phase8_bench --seeds 30 --out results/phase8
```

A CI definida no repositório cobre Linux, macOS e Windows com Python 3.10, 3.12 e 3.13. **Nenhuma plataforma deve ser marcada como validada até a execução correspondente do GitHub Actions terminar verde.**

## 4. Benchmark final e metodologia

O harness [`phase8_bench.py`](../../benchmarks/phase8/phase8_bench.py) criou dez famílias sintéticas independentes, com 30 seeds por família (300 sessões). Cada sessão tem três consultas de calibração e cinco holdout; o holdout não atualiza EMA de custo nem estatísticas de completude, embora a contagem de queries históricas avance como feature observável. Na família de mudança de regras são executadas três queries de aquecimento pré-transição, documentadas e fora das linhas medidas 3+5. Nas famílias de inserção/remoção, eventos de manutenção também ocorrem durante a calibração para estimar custo antes do holdout; no holdout, os valores são medidos e registrados, sem atualizar a política de custo.

As famílias são: grafos esparsos, grafos densos, cadeias de dependência, relações múltiplas, múltiplas provas, contradições, consultas com variáveis livres, inserções frequentes, remoções frequentes e mudanças de regras. As fixtures usam dez entidades e dados sintéticos determinísticos; não são dados reais nem treinamento. Cada sessão registra hash SHA-256 do snapshot, parâmetros, versões de software, métricas e sementes.

O oráculo é um avaliador exaustivo de ponto fixo independente do motor principal; cada estado também é verificado por recomputação completa com `InferenceEngine`. Estratégias fixas só entram na comparação de latência quando o resultado é completo e semanticamente igual ao oráculo. Métricas de backward incompleto ficam no CSV para auditoria, mas não são tratadas como vitória por serem rápidas. O delta pareado é `tempo total do controlador (decisão + execução) − tempo de execução fixa`, para a mesma consulta e somente nas linhas comparáveis.

### Resultados globais

- **2.400 consultas** registradas: 900 de calibração e 1.500 holdout.
- **300 sessões**, **30 seeds em cada família**.
- **0 divergências** entre controlador/oráculo ou recomputação completa/oráculo.
- **0 consultas holdout incompletas** do controlador.
- **240/240** inserções incrementais comparadas com recomputação completa coincidiram; 0 falhas.
- Todos os dez conjuntos tiveram 30 hashes iniciais distintos.
- RSS foi medido no processo no Linux; esses valores incluem o interpretador e o benchmark, não isolam a memória do grafo.
- A mediana agregada do tempo de conversão Rust foi **11,7 µs** e a construção nativa **257,2 µs** por snapshot nesta carga pequena. Refresh Rust teve mediana de **232,5 µs** em inserções e **213,8 µs** em remoções. São custos de conversão/construção/refresh separados; não são prova de aceleração end-to-end.

### Desempenho do controlador versus forward fixo

A tabela mostra holdout por família. Delta positivo significa que o controlador, incluindo o custo de decisão, foi mais lento que a estratégia forward fixa na mediana pareada. Delta negativo favorece o controlador nesta amostra; diferenças pequenas não demonstram vantagem geral.

| Família | Mediana total adaptativo (ms) | P95 observado (ms) | Decisão mediana (µs) | Delta pareado vs forward (ms), n | Resultado |
|---|---:|---:|---:|---:|---|
| Contradições | 0,055 | 0,076 | 29,1 | +0,033, 150 | pior |
| Grafos densos | 34,596 | 157,646 | 60,9 | +0,404, 150 | pior |
| Cadeias de dependência | 4,349 | 4,596 | 43,5 | +0,037, 150 | pior |
| Inserções frequentes | 2,251 | 4,807 | 47,2 | +0,039, 150 | pior |
| Remoções frequentes | 0,324 | 0,949 | 44,6 | +0,052, 150 | pior |
| Múltiplas provas | 0,063 | 0,086 | 42,7 | −0,019, 150 | melhor nesta amostra |
| Relações múltiplas | 9,365 | 15,985 | 57,1 | +0,027, 150 | pior |
| Variáveis livres | 17,750 | 146,403 | 45,1 | −0,148, 150 | melhor nesta amostra |
| Mudanças de regra | 0,060 | 0,104 | 40,3 | +0,002, 150 | pior |
| Grafos esparsos | 2,517 | 10,940 | 46,4 | +0,038, 150 | pior |

O seletor **não é declarado superior**: perdeu para o baseline forward na maioria das famílias; os dois deltas negativos são pequenos, e o caso de variáveis livres usa forward nos dois lados, portanto não indica vantagem algorítmica do seletor. As comparações com backward/hybrid, contagens de escolhas subótimas, operações, fatos/conclusões, RSS, manutenção e recomputação estão nos artefatos brutos. Backward teve menos comparações válidas em workloads nos quais não completou a busca; `n_comparable` documenta essa exclusão.

Medianas observadas por consulta holdout para trabalho e memória/manutenção (RSS do processo inclui Python e benchmark):

| Família | Operações | Fatos examinados | Conclusões | RSS final (MB) | Manutenção (µs) | Recomputação (ms) | Refresh Rust (µs) |
|---|---:|---:|---:|---:|---:|---:|---:|
| Contradições | 1 | 1 | 0 | 61,2 | 0 | 0,006 | 0 |
| Grafos densos | 9.834,5 | 9.833,5 | 100 | 49,8 | 0 | 20,710 | 0 |
| Cadeias de dependência | 2.986 | 2.985 | 45 | 59,7 | 0 | 4,244 | 0 |
| Inserções frequentes | 1.205 | 1.204 | 28 | 72,2 | 501,352 | 2,067 | 232,529 |
| Remoções frequentes | 75 | 74 | 6 | 72,7 | 3,939 | 0,241 | 213,772 |
| Múltiplas provas | 2 | — | — | 60,8 | 0 | 0,059 | 0 |
| Relações múltiplas | 4.565,5 | 4.564,5 | 69 | 60,3 | 0 | 8,991 | 0 |
| Variáveis livres | 4.331 | 4.330 | 66 | 71,6 | 0 | 8,147 | 0 |
| Mudanças de regra | 2 | — | — | 73,2 | 0 | 0,036 | 0 |
| Grafos esparsos | 1.440,5 | 1.439,5 | 32 | 25,7 | 0 | 2,540 | 0 |

### Artefatos

- `results/phase8/runs.csv`: 2.400 linhas de dados brutos por consulta.
- `results/phase8/summary.json`: resultados por família, pares comparáveis, hashes de cada sessão e métricas agregadas.
- `results/phase8/metadata.json`: ambiente, separação calibração/holdout e escopo das medições.

## 5. Estado da matriz CI e pendências

**CI final:** [run 42090138094](https://github.com/kalyeltonvieira/Aether/actions/runs/42090138094), SHA `0a71d3593221fa40e5cfad48864c1c028000794f`, terminou com sucesso em **9/9 jobs**: Ubuntu, macOS e Windows, cada um com Python 3.10, 3.12 e 3.13. Os nove jobs passaram build sdist/wheel, verificação de conteúdo do wheel e suíte completa. A correção decisiva separa a DLL nativa do `TemporaryDirectory` que os testes removem; `RustDynamicGraph.close()` também solta a referência ctypes, e as fixtures coletam ciclos. As execuções anteriores (42086731767 e 42089464628) falharam em Windows com `PermissionError`; os problemas foram corrigidos e a run final verde confirma a matriz pedida. A CI foi executada na branch `phase8`, sem merge.

Pendências/limites remanescentes:

1. A matriz exigida passou em todos os nove pares OS/Python no run 42090138094. Limites restantes são de escopo/compatibilidade documentados abaixo, não falhas CI pendentes.
2. Os workloads são sintéticos e pequenos; os números não se generalizam a grafos de produção ou às projeções SNAP.
3. Remoções e mudanças de regras usam recomputação conservadora quando a completude incremental não é demonstrável.
4. A integração Rust é medida quanto a conversão/construção/refresh; o controlador não seleciona um motor simbólico Rust e nenhum ganho end-to-end é alegado.
5. Confiança é dado declarado, não probabilidade calibrada; datas e outras proveniências ausentes permanecem `null`.
6. A alteração da identidade tipada exige reconstrução de chaves ao migrar snapshots antigos; não há migrador automático.
7. O controlador adaptativo perdeu para estratégia fixa em grande parte dos workloads e permanece experimental.

## 6. Critérios de aceitação

| Critério | Estado local | Evidência/pendência |
|---|---|---|
| Chaves tipadas sem colisões indevidas | Atendido | Testes bool/int/float/string/null e rejeição de compostos. |
| Provas alternativas preservadas | Atendido | Suportes alternativos, dependências por prova e invalidação testados. |
| Remoção conserva conclusão com prova alternativa | Atendido com recomputação conservadora | Tracker mantém prova restante; estado não é declarado completo antes de recomputar. |
| Consultas abertas enumeram soluções limitadas e explicadas | Atendido | Testes de bindings, explicações e completude. |
| Contradições explícitas sem resolução silenciosa | Atendido | Incompatibilidade declarada e resolução separada. |
| Lifecycle de regras | Atendido com recomputação | Versão/fingerprint e reasoner bloqueiam resultados obsoletos. |
| Incremental versus recomputação completa | Atendido para inserções medidas | 240/240 paridades; remoções usam recomputação. |
| Índice Rust detecta snapshot obsoleto | Atendido | Testes de stale, refresh e semântica direta/transitiva. |
| Python/Rust semanticamente equivalentes | Atendido nos testes executados | Matriz completa de SO ainda pendente. |
| Controlador avaliado em sessões reais de queries | Atendido como sequência sintética | 300 sessões; holdout congelado; resultados sem alegação de superioridade. |
| CI efetivamente passa nas plataformas | Atendido | Run 42090138094: 9/9 sucesso — Windows/macOS/Linux × Python 3.10/3.12/3.13. As runs anteriores que falharam permanecem registradas acima. |
| Benchmarks reproduzíveis | Atendido | 30 seeds/família, hashes, CSV/JSON e metadados. |
| Histórico anterior preservado | Atendido localmente | A branch parte da `main` auditada; sem merge automático. |

## 7. Publicação

A branch `phase8` foi publicada sem merge automático. Os problemas de teardown DLL encontrados em duas execuções foram corrigidos; a matriz final passou 9/9 em `0a71d35`.
