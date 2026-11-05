# AETHER — Auditoria inicial e plano da Fase 7

**Data:** 2026-11-05
**Branch:** `phase7`
**Base consolidada:** `origin/main` em `29e0eaa` (merge de `phase6new`)
**Estado inicial:** árvore limpa; `main`, `phase6`, `phase6new` e resultados históricos preservados.

## 1. Gate da Fase 6

A Fase 6 foi consolidada em `main` por meio do merge `29e0eaa`, depois da otimização de checkpoints publicada em `phase6new`. Sua suíte final passou em 73 testes, os cinco datasets SNAP disponíveis mantiveram seus hashes, e a restauração direta de linhas compactas reduziu o custo mediano de checkpoints adaptativos em 16,3% contra a medição anterior.

O gate de desempenho não é tratado como uma alegação universal: o controlador ainda perdeu marginalmente para a melhor rota fixa, a concorrência continuou mais lenta quando a construção de handles foi incluída, e Windows 10/11 não foi executado. Esses pontos serão carregados como limitações explícitas da Fase 7; o controlador não será ativado por padrão e não será usado para sustentar alegações de inteligência ou generalização.

## 2. Histórico preservado

- Fase 1: protótipo inicial e resultados arquivados.
- Fase 2: comparação de BFS, bitsets e fecho incremental, com ganhos condicionais a cargas estáticas.
- Fase 3: adjacência compacta, remoções exatas, memória menor e controlador ainda inferior a rotas fixas.
- Fase 4: ABI Rust/FFI end-to-end, com ganho forte em alcançabilidade sintética, mas sem alegação de inteligência geral.
- Fase 5: ABI v2, FFI em lote, SNAP real, cache, temporalidade, caminhos, vizinhança e componentes fracos.
- Fase 6: memória adaptativa, padrões, checkpoints, componentes incrementais, controlador e handles isolados; resultados negativos foram preservados junto dos ganhos.

Nenhum CSV, JSON, PNG ou relatório histórico será sobrescrito. Os novos benchmarks da Fase 7 ficarão em `results/phase7/`.

## 3. O que será reutilizado

### Reutilização direta

- `DynamicGraph` para semântica de adjacência mutável e consultas exatas quando uma relação de conhecimento for projetada para um grafo.
- `aether_adaptive_memory.py` apenas como infraestrutura operacional opcional; não será confundida com relevância semântica.
- `aether_checkpoints.py` como referência de replay, snapshots e invalidação temporal, sem reutilizar seus tipos como fatos de conhecimento.
- `aether_adaptive_controller.py` como componente experimental de medição de custo; não será promovido automaticamente, dada a perda observada na Fase 6.
- Testes, oráculos BFS/union-find, separação calibração/holdout, formato CSV/JSON e convenções de procedência.
- Rust/FFI somente se um benchmark demonstrar vantagem end-to-end e se a semântica puder ser preservada sem conversões ocultas.

### O que não será reutilizado como se fosse conhecimento

- Cache de alcançabilidade como memória semântica.
- Fecho transitivo como inferência explicável.
- Frequência de acesso como relevância.
- Um controlador empírico como aprendizado.
- Respostas de LLM, serviços externos ou dados inventados.

## 4. Arquitetura proposta, em incrementos pequenos

A Fase 7 será implementada em camadas independentes:

1. **Knowledge Store:** entidades, identificadores estáveis, propriedades, fatos direcionados, proveniência, confiança opcional explícita e deduplicação.
2. **Relation/Rule Engine:** relações tipadas e regras determinísticas auditáveis, com limites de profundidade, operações, conclusões e memória.
3. **Inference Engine:** forward chaining e backward/query-driven chaining mínimos, com profundidade e ciclo controlados; cada conclusão terá dependências.
4. **Dependency Tracker:** índice fato→conclusão e regra→conclusão para invalidar somente conclusões afetadas, com fallback visível para recomputação completa.
5. **Consistency Validator:** duplicatas, conflitos explícitos, ciclos proibidos conforme política e fatos sem proveniência; ausência de evidência retorna indeterminado.
6. **Explanation Engine:** trilhas compactas de fatos e regras, sem copiar a base inteira.
7. **Cost Controller:** comparação fixa/adaptativa apenas como componente experimental, incluindo custo de decisão.

A primeira implementação não tentará resolver ontologias abertas, linguagem natural, probabilidades não fundamentadas ou resolução automática de contradições.

## 5. Modelo de correção

O oráculo independente será uma implementação simples de recomputação completa, separada do motor incremental. Cada cenário terá:

- fatos positivos, negativos ou ausentes quando o modelo suportar a distinção;
- relações duplicadas e contraditórias;
- cadeias acíclicas e ciclos;
- inserções, remoções e atualizações;
- conclusões com profundidades conhecidas;
- justificativas esperadas como conjuntos de dependências.

A versão incremental só poderá ser chamada de incremental quando o contador de fatos examinados e as dependências confirmarem que a região não afetada foi reutilizada. Qualquer fallback será registrado nos CSVs.

## 6. Benchmarks planejados

Os principais cenários sintéticos terão pelo menos 30 seeds independentes, com seeds de calibração separados das seeds holdout:

- conhecimento pequeno, médio e grande;
- baixa e alta densidade de relações;
- profundidade de regra 1, 2, 4 e limite excedido;
- consultas positivas, negativas, ambíguas e contraditórias;
- inserção, remoção e atualização de fatos;
- inferência repetida com e sem cache;
- recomputação completa, incremental e incremental com cache;
- explicações curtas e profundas;
- operações que excedem limite de tempo, memória, profundidade ou conclusões.

Cada método receberá a mesma carga e o mesmo oráculo. Serão medidos latência, CPU, memória retida, fatos examinados, regras aplicadas, conclusões, invalidações, manutenção de dependências e custo de explicação.

Datasets públicos SNAP continuarão sendo usados somente como relações estruturais quando a transformação for documentada; eles não serão descritos como conhecimento semântico nem como dados de treinamento.

## 7. Riscos e limites

- A atualização incremental pode falhar em dependências compartilhadas; o fallback correto é preferível a uma conclusão obsoleta.
- Regras recursivas podem explodir combinações; todos os limites devem retornar estado explícito de execução incompleta.
- Proveniência e explicações podem custar mais memória que o fato; o custo será medido, não ocultado.
- Contradição não será resolvida automaticamente sem uma política declarada.
- O controlador da Fase 6 permanecerá opt-in se perder para uma estratégia fixa.
- Rust só será introduzido após prova quantitativa do benefício end-to-end.
- Não haverá claims de AGI, consciência, compreensão humana, aprendizado aberto ou inteligência geral.

## 8. Critério para seguir após esta auditoria

A auditoria está concluída e a branch está isolada. O primeiro commit posterior a este documento deverá conter somente a fundação do `Knowledge Store` e seus testes de invariantes. Cada camada seguinte será commitada separadamente, com testes antes da integração e sem modificar resultados anteriores.
