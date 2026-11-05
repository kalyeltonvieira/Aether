# Aether — Fase 2: diagnóstico e benchmark

## Resumo executivo

A principal descoberta é de política, não de superioridade universal do fecho transitivo: **manter todo o fecho é caro quando há inserções e poucas consultas; é vantajoso quando o grafo fica estático e há muitas consultas**. Foi adicionada uma rota adaptativa que estima custos de busca bitset e fecho por linhas e escolhe uma estratégia exata. Nos cinco perfis sintéticos avaliados, selecionou a estratégia com menor mediana em todos os casos; os coeficientes são calibrados apenas para este ambiente e família de cargas.

A versão original foi preservada, sem sobrescrever o protótipo ou os resultados iniciais, em `archive/v1/`.

## Diagnóstico baseado em perfil

No perfil `cProfile` do benchmark original, `IncrementalClosure.add` foi chamado 3.000 vezes e somou 1,221 s de tempo cumulativo profilerado (1,028 s próprio), enquanto `bfs` somou 0,453 s cumulativo (0,289 s próprio). O perfil contou 374.041 chamadas a `bit_length` e 19.826 a `bit_count`.

O custo vinha do trabalho algorítmico concreto: para cada inserção, o fecho percorria predecessores, aplicava a união de bitsets e, para cada relação nova, percorria bits alterados para atualizar uma transposta (`cols`). Essa transposta acelera a descoberta de predecessores, mas duplica informação e cria escritas por relação alcançável nova. No workload dinâmico, a arquitetura pagou pela construção e manutenção do fecho para 500 consultas aleatórias, enquanto BFS/bitsets computavam apenas o necessário por consulta. O perfil indica que não é correto atribuir toda a diferença ao Python, embora os loops Python amplifiquem o custo.

Os tempos profilerados são diagnósticos, não latências comparáveis às medições finais. O gerador sintético também constrói e embaralha uma lista de pares O(n²), mas isso ocorre fora da janela de tempo por algoritmo.

## Mudanças implementadas

1. `aether_engine.py` implementa uma API adaptativa reutilizável: estima custo antes de selecionar uma rota exata, entre busca em largura com adjacência bitset e fecho transitivo incremental por linhas.
2. O fecho por linhas remove a matriz transposta. Cada inserção varre as linhas para descobrir predecessores e atualiza somente linhas alcançáveis. Isso troca trabalho de varredura por menos duplicação.
3. `phase2_bench.py` mede separadamente construção, atualizações, consultas, total wall-clock e CPU do processo; mede RSS de pico em processos isolados e serializa o estado lógico para comparar armazenamento.
4. O benchmark compara BFS convencional, BFS de fronteira bitset, fecho legado com transposta, fecho Aether somente por linhas e o controlador.
5. `test_aether_engine.py` confere ambas as rotas contra BFS em 30 sementes, durante atualizações, além de validar previsões de rota e entradas inválidas.

A implementação completa em Rust, paralelismo, compressão adaptativa mais ampla e autootimização não foram adicionadas: os dados ainda não justificam essa complexidade.

## Protocolo

Cinco configurações, 30 sementes por configuração, cinco estratégias por semente: **750 execuções**. Cargas sintéticas dirigidas e determinísticas; os mesmos pares e consultas alimentaram todas as estratégias. Cada estratégia rodou em um processo filho para obter `ru_maxrss` isolado. O benchmark mediu wall-clock sem `cProfile` ou `tracemalloc`, e processo CPU separadamente. BFS serviu como oráculo. Os 750 registros concordaram exatamente com BFS.

O RSS físico medido inclui interpretador e a carga de entrada JSON, e sua resolução/contaminação pela entrada foi suficiente para que os valores ficassem iguais entre estratégias dentro de cada configuração. Portanto, **não se deve interpretar esse RSS como prova de igualdade de memória das estruturas**. O payload serializado mede o estado lógico, não overhead total de heap. Contadores são proxies de trabalho próprios, não FLOPs. Joules e FLOPs não foram medidos.

## Medianas finais

Tempos em ms; `Dual` mantém linhas e transposta; `Aether linhas` não mantém transposta. O controlador registra a rota efetivamente executada.

| Configuração | BFS | BFS bitset | Fecho dual | Aether linhas | Adaptativo / rota |
|---|---:|---:|---:|---:|---:|
| 60 nós, esparso, 60 inserções, 100 consultas | 0,402 | **0,368** | 1,073 | 0,586 | 0,360 / bitset |
| 120 nós, esparso, 240 inserções, 500 consultas | 3,718 | **2,763** | 7,573 | 3,951 | 2,872 / bitset |
| 120 nós, denso, 600 inserções, 500 consultas | 3,467 | **1,524** | 32,747 | 16,756 | 1,515 / bitset |
| 240 nós, esparso, 480 inserções, 1.000 consultas | 15,209 | **11,013** | 31,466 | 15,832 | 10,806 / bitset |
| 120 nós, estático, 20.000 consultas | 134,279 | 115,266 | 6,326 | **4,655** | 4,566 / Aether linhas |

Nas quatro cargas com atualizações, busca bitset venceu o fecho por linhas: o fecho foi de 1,43× a 10,99× mais lento, embora respondesse cada consulta em aproximadamente 0,014–0,139 ms após a construção. A busca bitset reduziu o tempo total em relação à BFS convencional nas quatro cargas dinâmicas. Na carga estática com 20 mil consultas, o Aether por linhas foi **24,76× mais rápido que BFS bitset** e **28,85× mais rápido que BFS convencional**. Essa vitória depende explicitamente de muita reutilização sobre um grafo sem atualizações.

Remover a transposta reduziu o payload serializado do fecho em aproximadamente 49,6–49,9% contra a versão dual nos cenários avaliados. A remoção também reduziu o tempo mediano do fecho legado em cerca de 26,4% no cenário estático; mesmo assim, o fecho por linhas ainda perde para BFS bitset nas quatro cargas dinâmicas. O estado Aether ainda é maior que o estado de adjacência esparsa em cenários estáticos comparáveis (2.124 B contra 1.547 B do bitset BFS, e 1.204 B da representação BFS por conjuntos).

O controlador selecionou bitset em 30/30 sementes nas quatro cargas dinâmicas e fecho por linhas em 30/30 na carga estática. Suas medianas ficaram próximas da rota selecionada, dentro da variação entre processos/seed. Seus coeficientes — estimativas simples em nanossegundos para scans de linhas, atualizações e consultas — foram ajustados neste runtime; eles **não são constantes universais**, não aprendem com tráfego inesperado e precisam de recalibração. A API recebe previsão do volume de trabalho; uma previsão ruim pode piorar desempenho, mas não afeta a exatidão.

## Custos de CPU, RAM e energia

O relatório JSON final inclui a mediana de `process_cpu_ms` por estratégia/cenário; CPU wall-clock e processo CPU são observações do processo local, não contagem de instruções. O RSS de pico inclui carga e interpretador e ficou pouco discriminativo. A comparação de payload serializado é mais informativa para o custo das estruturas neste protótipo, mas não representa consumo de disco real. Não havia medidor de energia disponível; nenhum joule foi estimado.

## Reprodução e conclusão

Na pasta do projeto:

```bash
python3 -m unittest -v test_aether_engine.py
python3 phase2_bench.py --seeds 30 --out results/phase2/final
```

**Conclusão:** o Aether original não demonstrava eficiência global. A Fase 2 reduz a duplicação da representação, acrescenta um motor selecionável e mede um nicho claro em que o fecho compensa: muitas consultas sem mudanças. Para grafos em evolução e workloads de baixa/média reutilização, a alternativa esparsa/bitset convencional vence. A arquitetura permanece experimental; esses testes sintéticos não provam eficiência em conhecimento aberto, dados reais, aprendizado geral ou outros hardwares.
