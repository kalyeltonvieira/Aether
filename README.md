# Projeto Aether — protótipo experimental de grafos e conhecimento relacional

O Aether reúne experimentos com grafos dinâmicos e raciocínio relacional. A hipótese original é limitada: **em uma sequência de inserções de arestas e consultas de alcançabilidade, manter o fecho transitivo atualizado pode reduzir o trabalho repetido por consulta**. Não é um sistema de inteligência geral, não usa LLM e não afirma aprender linguagem ou conhecimento aberto.

## Estado atual

A branch `main` contém a extensão `phase7new`. O relatório [`PHASE7_REPORT.md`](PHASE7_REPORT.md) é um registro histórico anterior; para o estado posterior, consulte [`PHASE7NEW_REPORT.md`](PHASE7NEW_REPORT.md). O escopo continua experimental: remoções com provas alternativas exigem recomputação para garantir completude, o controlador escolhe apenas entre estratégias implementadas e o backend Rust indexa relações diretas, sem executar as regras simbólicas.

## O que foi implementado

- Representação associativa: relações de alcançabilidade como bitsets por nó.
- Processamento por mudanças: inserção de uma aresta atualiza somente linhas de predecessores cujo alcance pode mudar.
- Composição/reuso: respostas posteriores consultam o estado previamente calculado, sem repetir BFS.
- Aprendizado incremental: cada aresta é incorporada sem reconstruir todo o fecho.
- Ativação e controle de custo: o caminho acionado na consulta e atualização percorre somente bits/predecessores relevantes; o protótipo **não** contém um estimador de benefício que decida ignorar trabalho.
- Compressão: bitsets compactam conjuntos de sucessores; pode haver custo quadrático em grafos densos.
- Autootimização: não implementada no protótipo; deixada como hipótese futura, não como capacidade alegada.

O comparador é busca em largura (BFS) sobre a adjacência, que responde consultas sob demanda. BFS também serve como oráculo independente para conferir exatidão. Cada algoritmo recebe a mesma sequência determinística de arestas e consultas. A saída falha explicitamente se as respostas divergirem.

## Executar

Requer Python 3.10+ e somente biblioteca padrão:

```bash
cd Aether
python3 aether_bench.py
```

## Instalação e dependências opcionais

O núcleo pode ser instalado como distribuição Python a partir do checkout:

```bash
python3 -m pip install .
```

O núcleo não exige dependências Python de runtime. Para gerar gráficos, instale `python3 -m pip install ".[plots]"`; para o comparador NetworkX, use `python3 -m pip install ".[networkx]"`. A integração Rust é opcional, mas requer Rust `1.99.1` (fixado em `rust-toolchain.toml`) e um linker adequado à plataforma; o wrapper compila a biblioteca na primeira utilização quando não há uma biblioteca compatível disponível.

Os scripts de benchmark e os testes continuam sendo executados a partir do checkout. A suíte completa e a construção de wheels/SDists são automatizadas em `.github/workflows/ci.yml`. A matriz da CI inclui Linux, macOS e Windows; suporte a uma plataforma só deve ser considerado validado após a execução verde do workflow nessa plataforma.

Parâmetros ajustáveis:

```bash
python3 aether_bench.py --nodes 120 --initial-edges 360 --updates 240 --queries 500 --repeats 5 --seed 20261104 --out results
```

O gerador usa `random.Random(seed)` para produzir workloads sintéticos reproduzíveis. Os resultados e metadados do ambiente são escritos em `results/benchmark.json` e `results/runs.csv`. Use múltiplos tamanhos/densidades e sementes antes de concluir que existe uma vantagem geral.

## Métricas e interpretação

- Latência: tempo de parede total para ingestão e consultas, em milissegundos; mediana sobre repetições. `tracemalloc` está ativo durante o tempo e acrescenta sobrecarga.
- RAM: pico de alocação Python rastreado por `tracemalloc`, não RSS total do processo nem consumo de memória física do sistema.
- Armazenamento: tamanho serializado lógico com pickle do estado final, não medida de arquivo de produção.
- Trabalho: visitas a arestas para BFS e contagem de atualizações de linha de bitset mais consultas no Aether. São contadores específicos de algoritmo, **não FLOPs comparáveis**.
- Precisão: concordância exata das respostas com BFS na carga executada. Isso verifica esta tarefa, não generalização.
- Custo de aprendizagem: está incluído no tempo total; não isolamos cada inserção em uma distribuição estatística separada.
- Dados: número de arestas iniciais e atualizações registrado; são gerados artificialmente, não amostra de dados reais.
- Energia/FLOPs: deixados como `null`; não há medidor de energia ou contagem de operações de ponto flutuante confiável no ambiente. Não inferir joules de CPU-segundos.

## Resultados e publicação

`results/` contém a execução deste ambiente. Para publicar externamente, preserve script, parâmetros, resultados brutos e descrição do hardware/software; não chame esta medição de estudo independente ou prova de superioridade. O benchmark aponta ganho apenas se a qualidade permanecer exata e a economia sobreviver a repetições, diversos tamanhos, densidades, razões atualização/consulta e baselines indexados. Deve-se reportar também casos em que o fecho fica denso e perde para BFS em memória ou custo de atualização.

## Limitações conhecidas

1. Grafo aleatório sintético simples, sem ruído, linguagem natural ou tarefas reais.
2. A comparação favorece cenários com consultas repetidas; uma consulta isolada pode favorecer BFS.
3. Fecho transitivo consome memória potencialmente quadrática. Em grafos densos, atualizações podem afetar muitas relações.
4. Sem medição direta de energia, FLOPs, armazenamento em disco, precisão em tarefas abertas ou dados mínimos para treinamento.
5. O benchmark tem valores fixos por padrão e não calibra automaticamente estatística de potência.
6. Um comparador convencional adicional, como índice de alcançabilidade otimizado, pode mudar os resultados.

## Próximos testes recomendados

Varredura cruzada de nós, densidades, proporção de consultas/atualizações e distribuição das consultas; pelo menos 30 sementes por ponto; baselines com BFS, bitset de fecho reconstruído em lote e índice apropriado; perfis de atualização e consulta separados; RSS por processo; joules com hardware/medidor identificado; registrar versão, CPU, política de frequência e ambiente isolado. Publicar todos os pontos e intervalos, incluindo perdas, em vez de só o melhor caso.

## Fase 2: comparação de estratégias e controlador

A implementação original foi preservada em `archive/v1/`. O harness independente `phase2_bench.py` compara BFS por conjuntos, busca de fronteira com bitsets de inteiros, fecho incremental com linhas+transposta e fecho incremental somente por linhas. A última alternativa evita manter a transposta e corta aproximadamente pela metade o payload serializado do fecho, ao custo de varrer todas as linhas a cada aresta.

Execute a bateria controlada com 30 sementes por cenário (cada estratégia em processo filho isolado):

```bash
python3 phase2_bench.py --seeds 30 --out results/phase2/final
```

As medições usam relógio de parede sem `cProfile`/`tracemalloc`, separam construção inicial, inserções e consultas e registram o pico RSS reportado pelo Linux (`ru_maxrss`, KiB), além do payload serializado. RSS inclui interpretador e carga de entrada; quando a entrada domina, o valor não distingue bem as estruturas internas. O contador de operações é específico de cada algoritmo, não equivale a FLOPs. Energia não é medida.

O controlador escolhe entre busca bitset e fecho somente por linhas com um modelo empírico explícito, reportando estratégia escolhida e ambos os custos estimados. Os coeficientes são calibrados neste ambiente e nesta família de grafos; devem ser recalibrados em outros hardwares ou workloads. A seleção muda o algoritmo exato de execução, não relaxa a exatidão.

### API do motor

`aether_engine.py` oferece `AdaptiveReachability`: informe `n`, as arestas iniciais, e estimativas de atualizações/consultas; consulte `engine.strategy` para inspecionar a escolha e use `add_edge(u, v)` / `reachable(u, v)`. Exemplo:

```python
from aether_engine import AdaptiveReachability

engine = AdaptiveReachability(
    120,
    initial_edges=[(0, 1), (1, 2)],
    expected_updates=0,
    expected_queries=20_000,
)
print(engine.stats())
print(engine.reachable(0, 2))
```

Previsões erradas podem escolher uma rota subótima, mas não alteram a correção das respostas. Para tráfego sem horizonte previsível, o controlador ainda é experimental: não faça forecast com confiança artificial; compare a alternativa escolhida com BFS/bitset em sua carga representativa antes de produção.

## Fase 3: escala, remoções e avaliação de Rust

`phase3_bench.py` compara `sets` e `array('I')` em grafos mutáveis de 1k/10k/100k nós, com DFS iterativa por conjunto, DFS com marcas de época e controlador online. A carga final é um DAG esparso com consultas positivas e negativas, e sentinelas que verificam uma relação antes/depois da remoção. Remoções refazem a resposta por busca na adjacência atual; não mantemos um fecho possivelmente obsoleto.

Reproduza com:

```bash
python3 -m unittest -v test_aether_dynamic.py test_aether_engine.py
python3 phase3_bench.py --seeds 5 --out results/phase3/final_release
```

A bateria final contém 75 processos e respostas exatas. O armazenamento compacto economizou aproximadamente 62,6–62,8% do heap estimado, porém a latência não melhorou em todas as escalas; o controlador perdeu para a melhor rota fixa. Consulte [`PHASE3_REPORT.md`](PHASE3_REPORT.md), [dados brutos CSV](results/phase3/final_release/runs.csv) e [resumo JSON](results/phase3/final_release/summary.json).

O perfil de 100k nós localizou o custo na DFS iterativa (`reachable_epoch`: 84,1% do tempo cumulativo do perfil). Só depois disso foi testado um microkernel Rust/CSR. Reproduza com `python3 rust_kernel_eval.py --seeds 5 --n 100000 --queries 90 --repetitions 10 --out results/phase3/rust_release` (requer `rustc`). O ganho mediano de aproximadamente 42,5× é **apenas do kernel**: construção/conversão, updates e integração não foram medidos. Consulte [relatório do perfil](results/phase3/profile/profile_100k.txt) e [resultados Rust](results/phase3/rust_release/summary.json); não extrapole esse fator para o sistema completo.

## Fase 4: integração Rust, memória e controle de custo

`aether_native.rs` compila como biblioteca compartilhada e `aether_native.py` fornece a API `RustDynamicGraph` via `ctypes`: `add_edge`, `remove_edge`, `has_edge`, `reachable`, `edge_count` e `close`. O grafo ativo é propriedade de Rust após uma importação em lote; não há cópia Python persistente da adjacência. Cada atualização/consulta paga uma chamada ABI; a construção/conversão Python→Rust é cronometrada. A representação nativa usa linhas mutáveis `Vec<Vec<u32>>`, não CSR, porque inserções/remoções precisam ser exatas. CSR imutável é medido separadamente apenas em workloads sem updates.

O benchmark compara Python sets, Python `array('I')` com épocas/pilha reutilizada, Rust FFI end-to-end, controlador online da Fase 3, política de memória v2, snapshot Python CSR e rebuild compacto a partir do conjunto ativo. Os perfis incluem cadeia esparsa com atalhos, consultas estáveis, mudanças de padrão, updates prolongados intercalados com consultas, componentes desconectados e um DAG pequeno de maior grau com janela limitada (não um grafo completo). As buscas e remoções são verificadas contra BFS independente; o harness falha em qualquer divergência.

```bash
python3 -m unittest -v test_aether_engine.py test_aether_dynamic.py test_aether_native.py
python3 phase4_bench.py --seeds 5 --large-seeds 1 --out results/phase4/final
python3 phase4_plot.py --summary results/phase4/final/summary.json --out-dir results/phase4
```

O `rustc` é obrigatório; gerar os gráficos requer `matplotlib` e `numpy` em Python. `--seeds` controla 1k/10k/100k e cargas query-heavy; `--large-seeds` controla 500k/1M, famílias de densidade/desconectadas e perfil prolonged. Os tamanhos máximos usam uma semente por padrão por custo de memória/CPU; isso deve aparecer como n=1 no relatório, não como significância estatística. O P95/P99 é gravado como `null` quando a execução tem menos de 100 consultas. O relógio ponta a ponta do worker inclui inicialização do processo e fronteira FFI, mas subtrai a validação BFS que ocorre após a medição; compilação Rust é informada separadamente.

Não há estimativa de joules nem FLOPs. RSS inclui o interpretador e buffers comuns de entrada; heap retido é estimativa (as capacidades Rust não incluem metadados do alocador). O controlador v2 decide antes da construção e nunca converte grafos vivos; seu custo decisório é medido. CSR é escolhido pelo controlador somente quando pressão do orçamento de memória o justifica, pois o piloto query-heavy mostrou que CSR puro em Python pode reduzir memória e ainda assim piorar latência. A política só será recomendada se a bateria final superar a melhor estratégia fixa no objetivo total medido.

Consulte [relatório Fase 3 com auditoria da divergência gráfico/tabela](PHASE3_REPORT.md), [relatório técnico Fase 4](PHASE4_REPORT.md), [CSV bruto Fase 4](results/phase4/final/runs.csv), [resumo JSON](results/phase4/final/summary.json), [gráfico de latência](results/phase4/phase4_latency.png) e [gráficos de memória](results/phase4/phase4_memory.png). A figura Fase 3 original foi preservada; a versão com rótulos corrigidos está em `results/phase4/phase3_release_consistent.png`.

## Fase 5: SNAP real, ABI v2, FFI em lote e novas capacidades

A Fase 5 adiciona ABI v2 com verificação de plataforma/arquitetura, importação e mutações em lote, buffer de saída reutilizável, consultas de menor caminho, vizinhança limitada, cache versionado e histórico temporal experimental. Também inclui componentes fracamente conectados, explicitamente distintos de componentes fortemente conectados. O controlador online e a política por características continuam experimentais; a rota fixa Rust não é substituída por um seletor sem evidência.

A reprodução completa dos dados reais requer Rust e os arquivos SNAP locais:

```bash
source "$HOME/.cargo/env"
python3 -m unittest discover -v
python3 phase5_download_snap.py
python3 phase5_bench.py --out results/phase5/real_data --seeds 3 --repeats 2 --queries 1000 --batch-size 8
python3 phase5_temporal_bench.py --out results/phase5/temporal_history
python3 phase5_components_bench.py --out results/phase5/components --repeats 3
python3 phase5_synthetic_bench.py --out results/phase5/synthetic_30seeds --seeds 30 --queries 100
python3 phase5_plot.py
```

A bateria concluída nesta sessão contém 240 benchmarks SNAP reais e 480 execuções sintéticas, todas exatas contra oráculos independentes. A comparação NetworkX foi executada separadamente em ambiente virtual, com 15 execuções e os mesmos hashes de workloads; NetworkX não é uma dependência do AETHER. Veja [relatório técnico da Fase 5](PHASE5_REPORT.md), [instalação multiplataforma](PHASE5_INSTALL.md), [pesquisa/procedência SNAP](PHASE5_SNAP_RESEARCH.md), [CSV/JSON reais](results/phase5/real_data/), [resultados sintéticos](results/phase5/synthetic_30seeds/), [componentes](results/phase5/components/) e [gráficos](results/phase5/plots/).

Windows 10/11 possui procedimento de compilação documentado, incluindo o linker MSVC, mas não foi executado nesta tarefa. Portanto, o código foi preparado para carregamento `.dll`/`.so`/`.dylib`, mas não se declara compatibilidade Windows medida.

## Fase 7: conhecimento estruturado e raciocínio relacional

A Fase 7 adiciona uma camada experimental em `aether_knowledge.py`, `aether_inference.py`, `aether_consistency.py`, `aether_dependencies.py` e `aether_reasoner.py`. Ela representa entidades, fatos tipados, propriedades, proveniência, regras determinísticas, conclusões com dependências e invalidação localizada. Inserções podem ser propagadas por agenda incremental; remoções com provas alternativas ainda requerem recomputação para garantir completude. Alterações feitas diretamente na `KnowledgeStore` depois da inferência agora invalidam a leitura de conclusões até uma recomputação.

Reproduza os testes e o benchmark controlado com:

```bash
python3 -m unittest discover -v
python3 phase7_bench.py --out results/phase7/knowledge_benchmark --seeds 30
```

O benchmark separa 15 seeds de calibração e 15 holdout em cada uma de duas famílias sintéticas. Os dados são fixtures de software, não treinamento e não conhecimento aberto. Resultados, procedência, CSV e gráfico ficam em `results/phase7/knowledge_benchmark/`; para os critérios e limites históricos, consulte [`PHASE7_REPORT.md`](PHASE7_REPORT.md) e leia o aviso de status deste README.

### Extensão phase7new: integração auditável e validação adicional

A extensão `phase7new`, agora integrada à `main`, adiciona a projeção semântica auditável do `email-Eu-core` (`aether_snap_semantic.py`), o controlador adaptativo (`aether_reasoning_controller.py`) e o índice relacional Rust end-to-end (`aether_knowledge_rust.py`). Reproduza com:

```bash
python3 -m unittest discover -v
python3 phase7new_controller_bench.py --seeds 30 --max-facts 1000
python3 phase7new_rust_bench.py --queries 1000
```

Consulte [`PHASE7NEW_REPORT.md`](PHASE7NEW_REPORT.md) e os artefatos em `results/phase7new/`. A projeção completa verifica o SHA-256 do manifesto e mantém a proveniência no `KnowledgeStore`; os benchmarks registram explicitamente quando medem uma amostra ou apenas a relação direta.

## Fase 8: semântica de provas, consultas e avaliação adaptativa

A Phase 8 preserva os experimentos anteriores e endurece as chaves escalares tipadas, o registro de provas alternativas, a invalidação por dependência, a enumeração de bindings para consultas abertas, o versionamento do índice Rust e o lifecycle de regras. O `KnowledgeReasoner` invalida resultados após mudanças de regra ou mutações externas e exige recomputação antes de declarar conclusões atuais. Incompatibilidades só são consideradas quando declaradas; conflitos e evidências permanecem armazenados e uma resolução é registrada separadamente.

Execute a suíte completa e os dez workloads determinísticos (30 seeds por família) com:

```bash
python3 -m unittest discover -v
python3 phase8_bench.py --seeds 30 --out results/phase8
```

O benchmark inclui grafos esparsos/densos, cadeias, relações múltiplas, provas alternativas, conflitos, variáveis livres, inserções, remoções e mudança de regras. Cada sessão separa três consultas de calibração de cinco consultas holdout; o holdout não atualiza EMA de custo nem estatísticas de completude (a contagem de queries históricas avança como feature observável). A família de mudança de regras também registra três consultas de aquecimento pré-transição, fora das linhas de calibração/holdout. `runs.csv`, `summary.json` e `metadata.json` guardam hashes, ambiente, métricas, comparações pareadas e indisponibilidades como `null`. A carga é sintética; os custos de conversão/construção/refresh Rust são reportados separadamente e **não** são usados para alegar superioridade end-to-end. O relatório [`PHASE8_REPORT.md`](PHASE8_REPORT.md) discrimina resultados efetivamente executados, estado da CI por plataforma e pendências.

## Licença

O código-fonte do projeto é disponibilizado sob a licença MIT, conforme [`LICENSE`](LICENSE). Isso não altera os termos dos datasets externos: arquivos SNAP não são incluídos na distribuição e devem ser obtidos e usados conforme as condições publicadas por suas fontes.
