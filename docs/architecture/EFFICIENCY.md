# Eficiência e otimização adaptativa

## Join planner experimental

`InferenceEngine`, `KnowledgeReasoner`, a atualização incremental, o fallback híbrido e o caminho forward do `AdaptiveReasoningController` aceitam `join_planner="input"` ou `"selective"`. `input` preserva a ordem da regra e continua sendo o padrão. `selective` estima a cardinalidade das antecedências por predicado e restrições constantes; em regras com seletividades diferentes, começa pela mais restrita, mas reconstrói os suportes na ordem original antes de emitir a prova. `JoinPlan` registra modo, ordem e estimativas.

O harness [phase9_efficiency.py](../../benchmarks/phase9/phase9_efficiency.py) comparou inferências completas em duas famílias sintéticas, 30 seeds por família, cinco repetições pareadas por estratégia e split 20 seeds de calibração + 10 de holdout. Cada resultado foi comparado por identidade de conclusões e de provas; todos terminaram completos. O tempo de execução inclui o planejamento e a construção das provas. Também foram registrados tempo de CPU, throughput derivado da p50 e fatos examinados.

| Família | Estratégia | p50 latência | p95 observado | p50 CPU | p50 fatos examinados |
|---|---|---:|---:|---:|---:|
| `selective_join` | `input` | 2,679 ms | 3,249 ms | 2,678 ms | 1.598 |
| `selective_join` | `selective` | 1,642 ms | 1,974 ms | 1,641 ms | 802 |
| `balanced_join` | `input` | 27,704 ms | 41,951 ms | 27,700 ms | 21.171 |
| `balanced_join` | `selective` | 27,739 ms | 41,979 ms | 27,736 ms | 21.171 |

No holdout seletivo, o planner atingiu 1,626× de speedup pareado mediano, reduziu fatos examinados em 49,8% e venceu em 10/10 seeds. No holdout balanceado, o ganho mediano foi nulo: `input` foi cerca de 0,2% mais rápido, sem redução de fatos examinados; `selective` venceu em 2/10 seeds. Por isso, o planner seletivo está disponível por configuração, mas **não foi promovido a padrão global**. Essa escolha evita pagar por estimativas sem benefício em workloads equilibrados.

O benchmark foi executado em Python 3.12.3, Linux ARM64 (`aarch64`), 6 CPUs disponíveis. O high-water RSS do processo completo foi 22.786.048 bytes e não é atribuído a uma estratégia individual. Não há resultado Windows nesta sessão; os números não devem ser extrapolados para x86_64/Windows. O [JSON detalhado](../../results/evolution/phase9_join_planner.json) contém os 60 seeds, metadados, split, medições e hash da fonte testada.

## Rust e concorrência

A integração Python/Rust existente continua cobrindo o índice de relações de grafo, com equivalência e invalidação de snapshots nos testes da fase 8. Esta etapa não moveu joins simbólicos para Rust: a medição mostra ganho na ordenação de trabalho em Python; o benchmark nativo abaixo mede benefício em reachability de grafo, não em unificação/provas. O Event Engine usa claims transacionais SQLite e preserva FIFO por serialização de um evento ativo; a escolha é de correção/ordem, não uma alegação de throughput paralelo.

## Limites

Os workloads do planner seletivo têm duas famílias sintéticas; o controller foi medido separadamente nas dez famílias do harness existente. Nenhum deles representa carga real de produção do Studio. Latência curta é sensível ao hardware e ao ruído do processo; p95 do planner é o percentil observado das 30 medianas por seed, não SLA de produção. Medição de energia não está disponível. A promoção do planner por padrão exige novos holdouts reais e benchmarking em Windows/Linux x86_64.

## Controller com disponibilidade de memória

O controller passou a amostrar memória física disponível e total com APIs portáveis; quando o host não fornece uma medida confiável, os campos são `None`. Pressão alta aumenta de maneira conservadora os priors de forward/híbrido e separa buckets históricos, mas não altera completude nem aceita transformar uma busca incompleta em resposta negativa. A amostra mede o host, não uma quota de cgroup; não deve ser apresentada como orçamento reservado à aplicação.

A execução complementar do harness existente da fase 8 cobriu **dez famílias × 30 seeds**, três consultas de calibração e cinco holdout por sessão: 2.400 consultas, zero divergências do oráculo, 240 comparações incrementais sem falhas e nenhum controller incompleto no holdout. Conversão/construção/refresh Rust foram medidos pelo harness existente, sem supor superioridade end-to-end. Os resultados estão em [controller_memory_holdout](../../results/evolution/controller_memory_holdout/summary.json), acompanhados de CSV, metadata e hashes adicionais.

O custo total adaptativo inclui decisão e execução. Ele perdeu para forward fixo equivalente em nove das dez famílias. Na família `open_variable_queries`, ganhou em 56,7% dos pares, mas escolheu necessariamente a mesma rota forward — isso não demonstra superioridade de seleção. Em consultas pequenas, a decisão custou mediana de cerca de 83–103 µs e dominou a execução. Portanto, **adaptive permanece uma opção experimental explícita**, enquanto a API/Studio utiliza forward fixo como padrão. A correção passou; a alegação de melhor eficiência geral não passou e não é feita.

## Benchmark nativo de custo completo

O novo [phase9_native.py](../../benchmarks/phase9/phase9_native.py) mediu duas famílias de grafos sintéticos de 128 nós, com 30 seeds por família e split 20/10. O ciclo inclui construção, 128 consultas, remoção de 20 arestas, mais 128 consultas, escrita/leitura JSON e reconstrução do grafo; custos de conversão e FFI são incluídos nos tempos Rust, com compilação do cdylib reportada separadamente. Um BFS exaustivo independente verificou Python, Rust individual, Rust em lote e as duas recuperações: zero divergências.

No holdout, o ciclo Rust foi 3,694× mais rápido no grafo esparso e 1,561× no denso, vencendo em 10/10 seeds em cada família. Consultas Rust em lote tiveram medianas de 0,171 ms (esparso) e 0,209 ms (denso), incluindo packing/FFI; chamadas individuais tiveram 0,353 ms e 0,351 ms. Os [dados completos](../../results/evolution/phase9_native.json) registram fonte/hashes, CPU, RSS e capacidades aproximadas de memória. As estimativas de heap Python e capacidade Rust não são medidas equivalentes de memória total.

Isso confirma benefício no backend de **reachability de grafo já existente**, não autoriza substituir joins/provas simbólicas por Rust nem demonstra paralelismo multiusuário. A recuperação medida é reconstrução a partir de uma lista JSON verificada pelo oráculo, não crash-consistency de um storage nativo. Compilação é custo de startup separado; resultados curtos não podem amortizá-lo automaticamente. Nenhum número de energia foi inventado.
