# AETHER — Fase 7new: fechamento das pendências da Fase 7

**Branch:** `phase7new`  
**Base:** `phase7` após o merge anterior e a atualização documental posterior.  
**Status:** implementação e validação final desta extensão concluídas; limitações técnicas explicitamente preservadas.

## Escopo fechado

Esta branch fecha as três pendências registradas no relatório anterior sem modificar a `main` nem reescrever os resultados históricos das Fases 1–6:

1. integração semântica auditável com um dataset público;
2. integração Rust end-to-end para a camada relacional de conhecimento;
3. controlador adaptativo de escolha entre backward, híbrido e forward.

A implementação foi separada em commits pequenos e verificáveis. A branch anterior `phase7` permanece preservada.

## Integração semântica SNAP

O módulo `aether_snap_semantic.py` transforma o arquivo oficial local `email-Eu-core.txt.gz` em um `KnowledgeStore`. Cada nó recebe o ID estável `snap:email-eu-core:node:<id>`. Cada linha dirigida `u v` gera o fato `u sent_email_to v`. Não há reversão de arestas, inferência de significado não documentado ou remoção silenciosa de linhas.

A execução reproduziu 1.005 entidades e 25.571 fatos únicos. O arquivo tinha 25.571 registros, zero duplicatas, zero linhas malformadas e SHA-256 `4b47acdb80197b085fe63c819c357ae488131ee904ed93d1b219a68b0f9e245f`. Cada fato mantém a URL oficial e a linha do arquivo em sua proveniência. Os artefatos estão em `results/phase7new/semantic_email_eu_core/`.

A semântica é deliberadamente restrita: o fato significa somente que o par dirigido aparece no arquivo SNAP. O sistema não afirma conhecer o conteúdo das mensagens, identidades pessoais ou causalidade social. A fonte e as condições de licença permanecem as registradas no manifesto da Fase 5 [1] [2].

## Controlador adaptativo

`AdaptiveReasoningController` mede o formato da consulta, a cardinalidade do predicado e o custo observado das execuções. Consultas abertas usam forward para obter fechamento; consultas ground esparsas começam por backward; após observações, o controlador usa uma média móvel exponencial do custo para selecionar entre as estratégias elegíveis. O custo de decisão é registrado separadamente e a escolha não altera a semântica do resultado.

No benchmark com 30 seeds sobre uma amostra explícita de 1.000 fatos da projeção auditada, houve 15 seeds de calibração e 15 de holdout. A distribuição foi de 20 escolhas backward e 10 forward; o híbrido ficou disponível, mas não foi selecionado neste workload. Todas as consultas holdout terminaram completas. A mediana do custo de decisão no holdout foi **5,046 μs** e a mediana do custo total foi **0,722 ms**.

A amostra de 1.000 fatos é uma decisão de custo do benchmark, não uma substituição da validação completa: a projeção completa de 25.571 fatos foi carregada e conferida antes da amostragem. Os resultados estão em `results/phase7new/controller_email_eu_core/`.

## Rust end-to-end

`RustKnowledgeIndex` usa a ABI v2 existente para construir um índice Rust de uma relação, mantendo `KnowledgeStore` como autoridade para IDs, propriedades e proveniência. A conversão para IDs densos e a construção do grafo são medidas separadamente. O Rust não recebe nem descarta a proveniência Python.

No dataset completo, com 1.005 entidades, 25.571 fatos e 1.000 consultas diretas, as respostas Rust coincidiram exatamente com as respostas do `KnowledgeStore`:

- consulta Python: **11,236 ms**;
- consulta Rust: **1,641 ms**;
- conversão: **29,913 ms**;
- construção Rust: **17,734 ms**;
- custo inicial total de conversão/construção: **47,647 ms**.

A consulta Rust foi aproximadamente 6,8× mais rápida neste lote. O custo inicial, porém, não é gratuito: pela diferença observada de 9,595 ms por lote, o ponto de equilíbrio aproximado é de cinco lotes equivalentes. Isso não é uma declaração de superioridade universal. O resultado justifica o índice Rust para reutilização em múltiplos lotes, mas não para uma única consulta ou para relações que exigem conversões frequentes.

A integração validada é relacional e direta. O Rust ainda não executa as regras simbólicas Horn nem armazena proveniência; essas responsabilidades permanecem no Python. Portanto, “Rust end-to-end” nesta branch significa caminho completo de fatos semânticos → conversão → índice nativo → consulta → comparação exata, e não um motor simbólico duplicado em Rust.

## Validação

A suíte completa foi executada após as três integrações: **108 testes passaram**, com **1 teste ignorado** por ausência do Rust no teste histórico que exige esse ambiente. Ela inclui os testes históricos da Fase 7, os testes da projeção SNAP, os testes do controlador adaptativo e o teste da ponte Rust.

Os artefatos principais são:

- `aether_snap_semantic.py` e `test_phase7_semantic.py`;
- `aether_reasoning_controller.py` e `test_phase7_controller.py`;
- `aether_knowledge_rust.py` e `test_phase7_rust_knowledge.py`;
- `phase7new_controller_bench.py`;
- `phase7new_rust_bench.py`;
- `results/phase7new/semantic_email_eu_core/`;
- `results/phase7new/controller_email_eu_core/`;
- `results/phase7new/rust_email_eu_core/`.

## Critérios consolidados

| Objetivo | Estado em `phase7new` |
|---|---|
| Conhecimento estruturado | Validado |
| Forward chaining | Validado |
| Backward chaining | Validado com enumeração de candidatos e limites explícitos |
| Estratégia híbrida | Implementada e medida |
| Inserções incrementais | Implementadas e medidas |
| Invalidação localizada | Validada |
| Remoções com provas alternativas | Recomputação continua necessária para garantir completude |
| Integração semântica com dados públicos | Atendida para a projeção documentada do `email-Eu-core` |
| Rust end-to-end | Atendido para índice relacional; regras e proveniência continuam no Python |
| Controlador adaptativo de raciocínio | Implementado, medido e limitado explicitamente ao espaço de estratégias suportado |
| Resultados históricos das Fases 1–6 | Preservados |

## Limitações que permanecem

A branch não transforma uma lista de arestas em compreensão de linguagem natural. A projeção semântica é uma relação formal e auditável, não conhecimento aberto. A invalidação de remoções com provas alternativas continua exigindo recomputação. O controlador adapta a seleção de estratégia, mas não aprende novas regras. O Rust acelera a relação indexada, mas não duplica o motor de inferência nem a camada de proveniência.

Essas limitações não são falhas ocultas: são fronteiras da implementação e aparecem nos sumários JSON e neste relatório. A `phase7new` atende os critérios de integração e medição solicitados para as três pendências, sem declarar que o sistema é um motor geral de conhecimento.

## Referências

[1]: https://snap.stanford.edu/data/email-Eu-core.html "SNAP email-Eu-core network"
[2]: https://snap.stanford.edu/data/index.html "Stanford Large Network Dataset Collection"
