# Projeto Aether — protótipo mínimo executável (arquivo histórico v1)

> Este diretório preserva o protótipo e seus resultados como registro histórico; não descreve o estado atual do AETHER. Para setup e uso atuais, consulte [setup geral](../../docs/development/SETUP.md), [setup Windows](../../docs/development/SETUP_WINDOWS.md), [setup Linux](../../docs/development/SETUP_LINUX.md) e [guia do Studio](../../docs/development/WEB_STUDIO.md).


Este protótipo testa uma hipótese limitada da arquitetura: **em uma sequência de inserções de arestas e consultas de alcançabilidade, manter o fecho transitivo atualizado pode reduzir o trabalho repetido por consulta**. Não é um sistema de inteligência geral, não usa LLM e não afirma aprender linguagem ou conhecimento aberto.

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
