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

A integração Python/Rust existente continua cobrindo o índice de relações de grafo, com equivalência e invalidação de snapshots nos testes da fase 8. Esta etapa não moveu joins simbólicos para Rust: a medição mostra o ganho em ordenação de trabalho em Python, enquanto não foi produzido benchmark end-to-end que inclua conversão, construção e FFI para justificar um port. O Event Engine usa claims transacionais SQLite e preserva FIFO por serialização de um evento ativo; a escolha é de correção/ordem, não uma alegação de throughput paralelo.

## Limites

Os workloads medidos são sintéticos e têm duas famílias, não representam ainda as dez famílias do harness da fase 8 nem carga real de Studio. Latência curta é sensível ao hardware e ao ruído do processo; p95 aqui é o percentil observado das 30 medianas por seed, não SLA de produção. Medição de energia não está disponível. A promoção do planner por padrão exige novos holdouts reais e benchmarking em Windows/Linux x86_64.
