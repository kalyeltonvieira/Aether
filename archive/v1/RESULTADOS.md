# Aether — resultado do primeiro microbenchmark

**Conclusão curta:** a implementação alcançou respostas exatas, mas **perdeu em latência e memória** no cenário padrão. Portanto, este teste inicial não demonstra vantagem de eficiência do Aether.

## Configuração

- 120 nós, 360 arestas iniciais, 240 inserções, 500 consultas;
- cinco execuções com sementes consecutivas a partir de 20261104;
- busca BFS sobre adjacência como baseline/oráculo;
- Python neste ambiente, com `tracemalloc` ligado durante a cronometragem.

## Medianas observadas

| Métrica | BFS | Aether incremental | Resultado |
|---|---:|---:|---|
| Latência total (ms) | 20,67 | 141,16 | Aether ~6,83× mais lento |
| Pico `tracemalloc` (bytes) | 77.488 | 84.524 | Aether ~9,1% maior |
| Estado serializado (bytes) | 1.692 | 2.176 | Aether ~28,6% maior |
| Contador de trabalho próprio | 53.474 visitas a arestas | 45.795 atualizações de linha + consultas | Contadores não equivalentes a FLOPs |
| Concordância com BFS | — | 100% | Todas as respostas conferidas |

## Leitura

O reuso do fecho reduziu seu contador interno de operações em relação às visitas de aresta da BFS, mas não compensou a sobrecarga do Python e do bitset atualizado nesta implementação e tamanho. A representação completa de alcançabilidade também ocupou mais memória que a adjacência esparsa. Este é um resultado negativo importante: contar menos operações abstratas não garante menor latência, energia ou memória reais.

## O que não foi medido

FLOPs, energia em joules, RSS físico do processo, dados reais, generalização, aprendizado em tarefas abertas e custo em aceleradores. Os números são de um workload artificial e de uma implementação de referência, não um benchmark independente. O campo de energia permanece nulo no JSON; não foi estimado a partir do tempo.

## Artefatos reproduzíveis

- Código e execução: `aether_bench.py` e `results/benchmark.json`.
- Medições linha a linha: `results/runs.csv`.
- Repita com `python3 aether_bench.py --nodes 120 --initial-edges 360 --updates 240 --queries 500 --repeats 5 --seed 20261104 --out results`.
