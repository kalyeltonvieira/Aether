# AETHER — Fase 7: conhecimento estruturado e raciocínio relacional

**Status:** validação intermediária da fundação; **Fase 7 ainda não deve ser declarada concluída**.
**Branch:** `phase7`
**Base:** merge consolidado da Fase 6 em `29e0eaa`.

## Resumo executivo

A Fase 7 adiciona uma camada experimental de conhecimento estruturado sobre o núcleo de grafos existente. A implementação atual representa entidades e fatos direcionados com identificadores estáveis, propriedades, proveniência opcional explícita, confiança limitada a valores fundamentados pelo chamador e índices por sujeito, predicado e objeto. Um motor determinístico aplica regras relacionais com encadeamento em múltiplas etapas, registra fatos de suporte, profundidade e regra usada, e impõe limites explícitos para operações, profundidade e conclusões.

Também foram adicionados validação de consistência e um rastreador de dependências. Remover um fato pode invalidar localmente conclusões descendentes sem varrer conclusões não relacionadas. A implementação é deliberadamente conservadora: adições marcam o estado como `stale` até recomputação explícita; remoções permanecem incompletas quando pode haver provas alternativas. Isso evita declarar processamento incremental completo quando a prova local ainda não é suficiente.

A suíte combinada passou em **102 testes** (1 ignorado por ausência de Rust no ambiente imediato). O benchmark v3 controlado gerou **420 registros**, com 30 seeds de calibração e 30 seeds holdout distribuídos em dois cenários sintéticos. Esses fixtures são cargas de software reproduzíveis, não dados de treinamento nem evidência de compreensão semântica aberta.

## 1. O que mudou na arquitetura

Os módulos novos são:

- `aether_knowledge.py`: entidades, fatos, propriedades, IDs determinísticos, proveniência, confiança, deduplicação e índices.
- `aether_inference.py`: padrões, regras Horn determinísticas, forward chaining limitado, profundidade e explicações por dependências.
- `aether_backward.py`: backward chaining query-driven limitado, com prova direta, ciclos e limites explícitos.
- `aether_hybrid.py`: estratégia híbrida que tenta backward para objetivos concretos e usa forward como fallback quando a prova query-driven não decide.
- `aether_consistency.py`: detecção de proveniência ausente, conflitos explícitos, ciclos proibidos, regras contraditórias e dependências inválidas.
- `aether_dependencies.py`: índice reverso fato/conclusão e invalidação localizada.
- `aether_incremental.py`: agenda de deltas para propagar inserções sem reemitir conclusões antigas.
- `aether_reasoner.py`: sessão segura que diferencia estado completo, estado stale e estado que precisa de recomputação.
- `phase7_bench.py`: benchmark com separação de calibração/holdout e procedência do fixture.

Os módulos de grafos, FFI Rust, memória adaptativa e checkpoints das Fases 1–6 não foram sobrescritos. Rust não foi atualizado nesta etapa porque ainda não existe evidência end-to-end de que uma representação nativa compense a conversão e a manutenção de proveniência; introduzir código nativo antes dessa medição seria complexidade sem justificativa.

## 2. Como o conhecimento é representado

Uma entidade possui um identificador textual estável e propriedades escalares. Um fato é uma tupla direcionada `(sujeito, predicado, objeto)`, com ID monotônico, proveniência opcional (`source`, evidência e instante observado), confiança opcional em `[0,1]` e propriedades próprias. A deduplicação opera sobre a tupla estrutural e não duplica índices nem incrementa a versão quando o mesmo fato é inserido novamente.

Os índices mantidos são sujeito→fatos, predicado→fatos e objeto→fatos. Consultas combinadas escolhem o índice de menor cardinalidade entre os filtros disponíveis e depois verificam os demais predicados. Isso evita uma varredura deliberada quando existe uma chave seletiva, embora o índice de propriedades de entidades ainda seja simples e não seja apresentado como índice semântico.

## 3. Relações, inferências e explicações

As regras são explícitas e determinísticas. Uma regra possui antecedentes com variáveis no formato `?x` e um consequente cujas variáveis devem aparecer nos antecedentes. O exemplo de transitividade usado nos testes é:

```text
(?x, connected, ?y) ∧ (?y, connected, ?z)
    -> (?x, connected, ?z)
```

O motor executa joins por predicado em ondas de profundidade. Conclusões repetidas não são duplicadas; ciclos terminam porque uma conclusão estrutural já conhecida não é emitida novamente. Cada `DerivedFact` registra regra, profundidade e suportes, que podem ser IDs de fatos explícitos ou chaves de conclusões derivadas.

A explicação recupera a conclusão solicitada e percorre somente as dependências derivadas necessárias, sem copiar o Knowledge Store. Ausência de conclusão retorna vazio/indeterminado; não há geração de resposta negativa como se fosse um fato provado.

O backward chaining recebe um objetivo concreto e tenta prová-lo primeiro por fato explícito; quando necessário, unifica o consequente de uma regra e busca seus antecedentes. Ele é query-driven e pode evitar gerar conclusões irrelevantes, mas a versão atual escolhe o primeiro candidato compatível para variáveis livres A estratégia híbrida usa esse comportamento de forma explícita: consultas prováveis são resolvidas query-driven; quando há variáveis livres ou ausência de decisão, o forward é usado como fallback. Limites reais continuam retornando estado incompleto.

## 4. Limites e segurança computacional

`InferenceLimits` controla profundidade máxima, operações máximas e número máximo de conclusões. Ao atingir um limite, o resultado contém `complete=False` e uma razão explícita como `max_depth`, `max_operations` ou `max_conclusions`. A API não apresenta uma lista parcial como conclusão completa.

A implementação não resolve automaticamente conflitos entre fatos incompatíveis, não inventa proveniência, não assume que frequência de acesso seja relevância semântica e não executa regras recursivas sem proteção contra duplicação e limites.

## 5. Atualizações incrementais

O `DependencyTracker` constrói um índice reverso a partir das trilhas existentes. Quando um fato explícito é removido, a invalidação percorre somente os dependentes alcançáveis no grafo de provas. Conclusões fora dessa região são preservadas. Se uma conclusão tiver provas alternativas, a sessão marca o estado como incompleto e exige `recompute()` antes de declarar o conjunto final exato.

Inserções agora usam uma agenda de deltas: o fato novo entra na fronteira, joins que o suportam produzem conclusões novas, e cada conclusão nova passa a ser uma fronteira para a próxima onda. O conjunto antigo não é reemitido. O custo de cada join ainda é contado; portanto, a implementação demonstra atualização incremental de inserções, mas não promete custo constante nem elimina toda leitura de fatos existentes. Se limites forem atingidos, o estado retorna incompleto explicitamente.

## 6. Validação quantitativa

O benchmark v3 foi executado com `python3 phase7_bench.py --out results/phase7/knowledge_benchmark_v3 --seeds 30`. Cada cenário usou 15 seeds de calibração e 15 seeds holdout; os registros foram mantidos em `runs.csv`. A medição mistura dois cenários controlados (`chain_sparse` e `chain_dense`), portanto `n=30` por método representa as duas famílias combinadas, não 30 datasets independentes. O fixture é sintético e não é dado de treinamento.

| Método no holdout | Latência mediana | P95 observado | Fatos/conclusões examinados | Interpretação |
|---|---:|---:|---:|---|
| Forward completo | 184,460 ms | 249,478 ms | 288.118 | produz o fechamento completo quando não excede limites |
| Backward query-driven | 0,807 ms | 2,730 ms | 769,5 | consulta concreta, sem gerar conclusões irrelevantes |
| Híbrido | 0,726 ms | 2,652 ms | 769,5 | escolheu backward neste workload; fallback forward permanece disponível |
| Inserção incremental | 116,236 ms | 290,354 ms | 200.281 | reduz mediana em relação ao recompute, mas ainda percorre muitos fatos |
| Lookup de conclusão em cache | 1,037 ms | 2,561 ms | 0 | reutiliza conclusões já produzidas |
| Explicação | 0,367 ms | 0,544 ms | 2,5 | custo de trilha curta neste fixture |
| Invalidação localizada | 0,038 ms | 0,054 ms | 18,5 | 17,5 conclusões invalidadas; não refaz o fechamento |

No holdout, o backward foi aproximadamente 229 vezes mais rápido que o forward completo pela mediana observada, mas essa não é uma comparação de tarefas idênticas: backward responde um objetivo concreto e forward calcula o fechamento. O híbrido ficou aproximadamente 11% abaixo do backward na mediana neste fixture e não acionou fallback; isso não autoriza generalizar superioridade para consultas abertas ou outros grafos.

A inserção incremental reduziu a mediana de 184,460 ms para 116,236 ms, cerca de 37%, mas seu P95 foi maior que o do forward (290,354 ms contra 249,478 ms) e ainda examinou 200.281 fatos. Portanto, a agenda é funcional e útil para algumas inserções, mas não é custo constante nem sempre vence a recomputação.

A calibração teve forward de 177,778 ms, backward de 1,116 ms, híbrido de 1,004 ms e inserção incremental de 142,426 ms. O holdout teve forward de 184,460 ms, backward de 0,807 ms, híbrido de 0,726 ms e inserção incremental de 116,236 ms. Os dados brutos, sumários JSON e procedência estão em `results/phase7/knowledge_benchmark_v3/`.

## 7. O QUE A AETHER CONSEGUE RACIOCINAR NA FASE 7

Com fatos explícitos `a connected b`, `b connected c` e uma regra transitiva, o sistema consegue derivar `a connected c`, registrar que a regra `transitive-link` foi aplicada e recuperar os dois fatos que sustentaram a conclusão. Com uma cadeia de quatro entidades, consegue produzir conclusões em profundidades sucessivas e impedir duplicação quando a cadeia fecha um ciclo.

Também consegue dizer que uma conclusão não está determinada quando não há fatos que a sustentem. Consegue detectar que `a active b` e `a inactive b` formam um conflito quando essa incompatibilidade é declarada pelo chamador, e consegue sinalizar um ciclo numa relação configurada como acíclica. Após a remoção de um fato, consegue retirar conclusões dependentes da trilha conhecida sem apagar conclusões não relacionadas.

Esses exemplos são raciocínio simbólico restrito sobre relações fornecidas. Não são compreensão de linguagem natural, conhecimento aberto, aprendizado geral ou inteligência geral.

## 8. Comparação com as Fases 5 e 6

A Fase 5 mediu alcançabilidade e operações estruturais em SNAP real, com 240 benchmarks, ABI Rust v2 e consultas em lote. A Fase 7 opera sobre tuplas e regras simbólicas e, portanto, suas latências não são diretamente comparáveis às latências SNAP. O ponto reutilizado é metodológico: IDs estáveis, oráculos independentes, CSV bruto, hashes/procedência e separação entre custo de construção e consulta.

A Fase 6 mediu memória operacional, checkpoints, componentes, controlador e handles concorrentes. Sua principal lição carregada para a Fase 7 é não declarar uma política adaptativa padrão quando ela perde para a melhor fixa. A Fase 7 aplica a mesma cautela: o rastreador incremental é uma camada opt-in e não substitui recomputação quando há dependências alternativas não resolvidas.

Não há comparação numérica direta entre os milissegundos da Fase 7 e os das Fases 5–6, porque os workloads, objetivos, tamanhos, hosts e janelas de medição diferem. O relatório preserva essa incomparabilidade em vez de normalizar números por cálculo arbitrário.

## 9. Critérios de conclusão

| Critério | Estado nesta etapa |
|---|---|
| Representação de conhecimento funcional | Atendido para entidades, fatos e índices direcionados |
| Inferências reproduzíveis | Atendido para regras determinísticas nos fixtures testados |
| Conclusões com proveniência | Atendido para dependências de fatos e regras; proveniência de fatos pode estar ausente e é diagnosticada |
| Alterações invalidam/atualizam conclusões afetadas | Atendido para invalidação localizada e inserções por agenda; provas alternativas após remoções ainda exigem recomputação |
| Proteção contra ciclos/explosão | Atendido por deduplicação e limites configuráveis |
| Testes independentes | Atendido: 102 testes combinados passaram; 1 ignorado por Rust ausente no ambiente imediato |
| Custo computacional documentado | Atendido no benchmark sintético de 30 seeds e duas famílias |
| Benchmarks reproduzíveis | Atendido para o benchmark sintético; SNAP semântico ainda não integrado |
| Resultados históricos preservados | Atendido; nenhum artefato das Fases 1–6 foi sobrescrito |
| Rust atualizado/integrado | Não atendido nesta etapa; ainda sem justificativa quantitativa end-to-end |
| Forward/backward/híbrido comparados | Atendido para o workload controlado; backward e híbrido são query-driven e não substituem forward para fechamento completo |
| Holdout com controlador adaptativo de estratégia | Não atendido; controlador permanece o da Fase 6 e não foi promovido |
| Dataset público com transformação semântica auditável | Não atendido; SNAP continua estrutural, não semântico |

### Situação consolidada

| Objetivo | Situação documentada |
|---|---|
| Conhecimento estruturado | Validado |
| Forward chaining | Validado |
| Backward chaining | Validado |
| Estratégia híbrida | Implementada e medida |
| Inserções incrementais | Implementadas e medidas |
| Invalidação localizada | Validada |
| Remoções com provas alternativas | Recomputação necessária |
| Integração semântica com dados públicos | Pendente |
| Rust end-to-end | Pendente |
| Controlador adaptativo de raciocínio | Pendente |

**Veredito:** a fundação estruturada da Fase 7 é funcional e validada em testes e benchmark controlado, mas a Fase 7 completa ainda não está concluída. A Fase 7 ainda não deve ser declarada totalmente concluída: integração semântica auditável com dataset público e avaliação Rust end-to-end continuam pendentes. A comparação de raciocínio e a agenda incremental já foram implementadas e medidas, sem esconder que o ganho incremental tem cauda pior e alto custo de leitura.

## 10. Artefatos e reprodução

```bash
cd Aether
python3 -m unittest discover -v
python3 phase7_bench.py --out results/phase7/knowledge_benchmark_v3 --seeds 30
```

Artefatos principais:

- `phase7_bench.py`
- `aether_hybrid.py` e `test_phase7_hybrid.py`
- `results/phase7/knowledge_benchmark_v3/runs.csv`
- `results/phase7/knowledge_benchmark_v3/summary.json`
- `results/phase7/knowledge_benchmark_v3/provenance.json`
- `results/phase7/knowledge_benchmark_v3/phase7_knowledge_benchmark.png`
- `PHASE7_AUDIT.md`
