# Aether — Fase 4: integração nativa, escalabilidade e adaptação

## Resumo executivo

A Fase 4 investigou um gargalo já localizado na Fase 3: a travessia DFS iterativa em Python. Foi implementado um backend Rust mutável ligado por `ctypes`, medido junto da construção, atualizações, consultas e custo de processo. A biblioteca mantém o grafo após uma importação em lote; não conserva uma segunda adjacência Python. As remoções e respostas continuaram exatas em todos os comparadores.

A bateria oficial executou **342 processos em 57 configurações**: cinco sementes para os pontos regulares de 1k, 10k e 100k nós e para 3.000 consultas estáticas; uma semente para os workloads prolongados, desconectados e de maior grau, e para 500k/1M nós. **342/342 execuções concordaram com BFS independente**; não houve divergência de resposta nem falha nas sentinelas de remoção/restauração.

O backend Rust FFI apresentou a evidência mais forte desta fase: no workload esparso com updates (`churn`), reduziu o tempo medido de construção+updates+consultas em aproximadamente **69% a 88%** frente à melhor implementação Python fixa nas escalas com cinco sementes e em **70% a 74%** nos pontos de 500k e 1M (estes últimos têm uma semente). Em 1M nós, por exemplo, a mediana foi **231,4 ms** contra **886,9 ms** da melhor rota Python fixa; o RSS incremental medido caiu de **104,4 MB** para **55,8 MB**, e o heap retido estimado de **111,4 MB** para **46,1 MB**. Isso é evidência promissora para **esta tarefa de alcançabilidade em grafos sintéticos**, não demonstra uma arquitetura geral de IA eficiente.

O controlador legado perdeu para a melhor implementação Python fixa nas configurações avaliadas. A nova política de representação teve resultados mistos: em 500k nós escolheu `sets`, embora `array('I')` fosse mais rápido e ocupasse menos memória; não demonstrou vantagem robusta para recomendar ativação padrão. A estratégia de reconstruir o snapshot após checkpoints foi muito mais lenta nas cargas grandes e reteve mais memória. Python CSR economizou bastante memória, mas foi mais lento nas cargas estáticas testadas.

## Protocolo e comparadores

Cada método foi executado em um processo isolado com a mesma carga determinística. O benchmark separa construção, atualizações, reconstruções, consultas e CPU do processo. A métrica `workload_wall_ms` cobre construção, updates e consultas/eventos, sem startup do worker; `e2e_wall_ms_including_worker_startup` inclui inicialização do worker e fronteira FFI, mas exclui a validação BFS feita depois da medição. A compilação da biblioteca Rust foi medida separadamente e consta no JSON.

Os métodos são: Python sets com DFS e conjunto de visitados; Python com adjacência `array('I')`, marcas de época e pilha reutilizada; Rust `Vec<Vec<u32>>` mutável via FFI; controlador online da Fase 3; política v2 de custo/memória; snapshot Python CSR (somente workloads estáticos); e rebuild compacto a partir do conjunto ativo de arestas em checkpoints explícitos. O rebuild registra separadamente updates e tempo de reconstrução.

Os workloads incluem DAG esparso de cadeia com atalhos (`stable`, `churn`, `shift` e `prolonged`), 3.000 consultas estáticas, quatro componentes desconectados e um DAG de maior grau com janela forward limitada. O último tem cerca de **6,3% das arestas possíveis de um DAG de 1.000 nós**; portanto, é um teste de grau/densidade maior que o baseline esparso, não um grafo completo. A carga desconectada mantém cerca de 0,27% das arestas possíveis no mesmo tamanho. Os workloads dinâmicos incluem consultas antes e depois das mudanças; uma sentinela exige que uma relação seja verdadeira, falsa após remoção e verdadeira novamente após restauração.

A implementação de Rust foi avaliada somente após o perfil da Fase 3 atribuir aproximadamente 84,1% do tempo cumulativo instrumentado à travessia DFS. O backend Rust foi validado contra um oráculo Python independente após a execução cronometrada.

## Latência e CPU

Medianas do `workload_wall_ms`. Para cada linha, “Python fixa” é a rota mais rápida entre `python_current` e `python_optimized` no mesmo cenário. Os percentuais são a redução de Rust frente a essa mediana Python. Os tempos end-to-end incluem startup do worker e estão sujeitos ao custo comum de inicialização nos casos pequenos.

| Nós / carga | Sementes | Melhor Python fixa | Rust FFI | Redução de workload | E2E Python → Rust |
|---|---:|---:|---:|---:|---:|
| 1.000 · churn, 120 consultas | 5 | sets · 5,406 ms | 1,674 ms | 69,0% | 42,586 → 39,844 ms (−6,4%) |
| 10.000 · churn, 90 consultas | 5 | sets · 38,328 ms | 4,500 ms | 88,3% | 83,734 → 43,050 ms (−48,6%) |
| 100.000 · churn, 36 consultas | 5 | compact · 177,174 ms | 30,473 ms | 82,8% | 241,202 → 88,742 ms (−63,2%) |
| 100.000 · shift, 36 consultas | 5 | compact · 89,534 ms | 27,863 ms | 68,9% | 153,783 → 86,560 ms (−43,7%) |
| 100.000 · prolonged, 90 consultas e 1.602 mudanças | 1 | sets · 381,747 ms | 35,752 ms | 90,6% | 468,277 → 90,144 ms (−80,7%) |
| 500.000 · churn, 8 consultas | 1 | compact · 417,245 ms | 123,787 ms | 70,3% | 565,095 → 245,482 ms (−56,6%) |
| 1.000.000 · churn, 8 consultas | 1 | compact · 886,905 ms | 231,438 ms | 73,9% | 1.152,100 → 423,043 ms (−63,3%) |

A redução de CPU de processo acompanhou de perto a redução de `workload_wall_ms`: por exemplo, 82,8% em 100k churn e 73,9% em 1M churn. No teste de 1k nós, o tempo da tarefa caiu 69%, mas a métrica com startup caiu somente 6,4%; isso mostra por que latência de kernel e latência do sistema não devem ser confundidas.

Nas cinco sementes de 100k churn, Rust ficou entre **30,158 e 31,073 ms**; a rota Python compacta ficou entre **171,625 e 179,170 ms**. Em 10k churn, Rust variou de **4,465 a 4,575 ms**; o baseline sets variou de **37,595 a 53,412 ms**, com um outlier de host visível. Os dados brutos permitem recalcular as variações; não foram inferidos intervalos de confiança a partir de cinco sementes.

## Memória e armazenamento

A estimativa de heap retido inclui estruturas mantidas e buffers de busca; para Rust usa capacidades das linhas mais marcas/pilha. Não inclui todos os metadados internos do alocador. RSS é o residente real do processo e inclui interpretador/entrada; o delta é medido após construção e antes de liberar o buffer comum de importação. Logo, RSS e heap estimado respondem a perguntas diferentes.

| Nós · churn | Heap Python compacto → Rust | Redução heap | Delta RSS compacto → Rust | Redução RSS |
|---|---:|---:|---:|---:|
| 10.000 | 1,115 → 0,456 MB | 59,0% | 1,077 → 0,676 MB | 37,2% |
| 100.000 | 11,078 → 4,662 MB | 57,9% | 10,437 → 5,526 MB | 47,1% |
| 500.000 | 55,611 → 23,049 MB | 58,6% | 52,183 → 27,918 MB | 46,5% |
| 1.000.000 | 111,376 → 46,097 MB | 58,6% | 104,362 → 55,808 MB | 46,5% |

Em 1M nós, a lista de arestas empacotada em pares de IDs de 32 bits teria payload lógico de cerca de 10,67 MB; um snapshot CSR com índices de 32 bits e offsets de 64 bits, cerca de 13,33 MB. Estes campos são **tamanhos de payload binário calculados**, não tempos nem medições de arquivos serializados em produção. O estado Rust mutável tem overhead adicional em relação a esses formatos compactados, mas ainda reteve menos heap/RSS que os backends Python medidos.

O CSR Python ilustra um trade-off: em 1k nós e 3.000 consultas, reteve cerca de **18 KB** contra **262 KB** de sets, mas sua carga total foi **170,8 ms**, contra **104,0 ms** de Python sets. No grafo de maior grau, CSR reteve 0,142 MB contra 3,122 MB de sets, mas levou 19,0 ms contra 13,8 ms. Menos memória não garantiu menor custo total.

## Controladores e rebuild

O controlador legado foi mais lento que a melhor rota Python fixa em todas as famílias resumidas. Em 10k churn, foi cerca de 10,8% mais lento; em 100k churn, 1,5% mais lento; em 1M churn, 8,2% mais lento. Em 3.000 consultas, o controlador fez em mediana 35 sondagens e uma troca de rota, consumindo cerca de **4,0 ms** em decisões/atualizações de controle. **Não é recomendável como padrão.**

A política v2 decide uma representação antes de construir o grafo; não converte estruturas ativas. O custo da decisão aparece separado. Seus resultados foram mistos: ficou 7,7% mais lenta que a melhor Python fixa em 10k churn, aproximadamente empatada em 100k churn e 35,0% mais lenta em 500k, onde escolheu sets em vez do backend compacto que venceu. Em 1M escolheu compacto, mas esse resultado tem uma única semente. Isso não demonstra que o seletor compensa o custo nem que seus limiares generalizam; mantenha-o experimental.

O método `python_rebuild` guarda um conjunto ativo e reconstrói um snapshot compacto nos checkpoints. Em 100k churn, reconstruiu por aproximadamente **239 ms** e totalizou 446,8 ms, contra 177,2 ms do backend compacto atualizado in-place. Em 100k prolonged, a reconstrução somou 2,287 s; em 1M churn, 3,768 s e 5,783 s de workload total. A estratégia também retém o conjunto de arestas e o snapshot, usando cerca de 2,7–2,9× o heap do compacto nas cargas grandes. Neste protocolo, updates in-place foram claramente preferíveis.

## Precisão, dados e métricas não disponíveis

Todas as respostas das 342 execuções concordaram exatamente com o BFS independente; a taxa de erro observada foi **0%**. As cargas são grafos dirigidos sintéticos, não dados de treinamento. Não há quantidade de amostras de treino a reportar: este protótipo resolve alcançabilidade sobre relações fornecidas e **não aprende conhecimento aberto nem linguagem**. Os CSVs registram nós, arestas, consultas, updates e respostas positivas/negativas por execução.

CPU foi medida por `process_time` e latência por relógio monotônico. P50 foi calculado em todas as execuções; P95/P99 são `null` quando há menos de 100 consultas no processo. **FLOPs não são uma medida apropriada para comparar estas travessias inteiras e não foram fabricados. Energia em joules não foi medida**; CPU-segundos não foram convertidos em energia. Também não foi medido armazenamento em disco de grafos serializados.

## Limitações e decisão

- Os resultados vêm de cargas DAG sintéticas em um host AMD EPYC x86_64 com 6 CPUs lógicas e cerca de 25 GB de RAM visíveis; frequência, energia e exclusividade do host não foram controladas.
- A bateria regular tem cinco sementes; famílias de maior grau/desconexão, perfil prolonged e escalas de 500k/1M usam uma semente. Os últimos pontos mostram que o protótipo executa nessas escalas, mas não sustentam inferência estatística robusta.
- A carga prolongada representa updates em blocos com consultas entre checkpoints, não tráfego concorrente ou um banco de produção.
- Não há comparação com bibliotecas nativas especializadas de grafos, discos, grafos densos completos em grande escala, workloads multithread ou medição direta de energia.
- O FFI ainda faz uma chamada por update/consulta. Uma API em lote poderia alterar o equilíbrio em tarefas pequenas.
- Resultados dependem de compilação `rustc -O`, versão do Python, host e distribuição de graus.

**Decisão experimental:** a integração Rust é promissora para acelerar alcançabilidade exata neste workload, inclusive após incluir construção/importação, updates, consultas e startup. A vantagem fica menor em cargas muito pequenas, mas persiste nas escalas e perfis testados. O próximo passo deve ser validar em grafos reais e com workloads independentes, testar uma API FFI em lote e medir energia em hardware instrumentado. Os controladores atuais, a reconstrução e a hipótese de inteligência/eficiência geral não passam ainda o critério de sucesso.

## Reprodução e artefatos

```bash
python3 -m unittest -v test_aether_engine.py test_aether_dynamic.py test_aether_native.py
python3 phase4_bench.py --seeds 5 --large-seeds 1 --out results/phase4/final
python3 phase4_plot.py --summary results/phase4/final/summary.json --out-dir results/phase4
```

O benchmark recompila `aether_native.rs`; o binário gerado é ignorado pelo Git. Resultados brutos: [`runs.csv`](results/phase4/final/runs.csv) e [`summary.json`](results/phase4/final/summary.json). Gráficos: [latência total](results/phase4/phase4_latency.png), [memória](results/phase4/phase4_memory.png) e [CSR query-heavy](results/phase4/phase4_queryheavy.png). O [README](README.md) contém a visão geral e o relatório da [Fase 3](PHASE3_REPORT.md) registra a correção da divergência entre gráfico e tabela anterior.
