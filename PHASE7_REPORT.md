# AETHER — Fase 7: conhecimento estruturado e raciocínio relacional

**Status:** validação intermediária da fundação; **Fase 7 ainda não deve ser declarada concluída**.
**Branch:** `phase7`
**Base:** merge consolidado da Fase 6 em `29e0eaa`.

## Resumo executivo

A Fase 7 adiciona uma camada experimental de conhecimento estruturado sobre o núcleo de grafos existente. A implementação atual representa entidades e fatos direcionados com identificadores estáveis, propriedades, proveniência opcional explícita, confiança limitada a valores fundamentados pelo chamador e índices por sujeito, predicado e objeto. Um motor determinístico aplica regras relacionais com encadeamento em múltiplas etapas, registra fatos de suporte, profundidade e regra usada, e impõe limites explícitos para operações, profundidade e conclusões.

Também foram adicionados validação de consistência e um rastreador de dependências. Remover um fato pode invalidar localmente conclusões descendentes sem varrer conclusões não relacionadas. A implementação é deliberadamente conservadora: adições marcam o estado como `stale` até recomputação explícita; remoções permanecem incompletas quando pode haver provas alternativas. Isso evita declarar processamento incremental completo quando a prova local ainda não é suficiente.

A suíte combinada passou em **101 testes**. O benchmark controlado gerou **240 registros**, com 30 seeds de calibração e 30 seeds holdout distribuídos em dois cenários sintéticos. Esses fixtures são cargas de software reproduzíveis, não dados de treinamento nem evidência de compreensão semântica aberta.

## 1. O que mudou na arquitetura

Os módulos novos são:

- `aether_knowledge.py`: entidades, fatos, propriedades, IDs determinísticos, proveniência, confiança, deduplicação e índices.
- `aether_inference.py`: padrões, regras Horn determinísticas, forward chaining limitado, profundidade e explicações por dependências.
- `aether_backward.py`: backward chaining query-driven limitado, com prova direta, ciclos e limites explícitos.
- `aether_consistency.py`: detecção de proveniência ausente, conflitos explícitos, ciclos proibidos, regras contraditórias e dependências inválidas.
- `aether_dependencies.py`: índice reverso fato/conclusão e invalidação localizada.
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

O backward chaining recebe um objetivo concreto e tenta prová-lo primeiro por fato explícito; quando necessário, unifica o consequente de uma regra e busca seus antecedentes. Ele é query-driven e pode evitar gerar conclusões irrelevantes, mas a versão atual escolhe o primeiro candidato compatível para variáveis livres e ainda não foi comparada quantitativamente ao forward em uma bateria separada. Essa limitação permanece aberta.

## 4. Limites e segurança computacional

`InferenceLimits` controla profundidade máxima, operações máximas e número máximo de conclusões. Ao atingir um limite, o resultado contém `complete=False` e uma razão explícita como `max_depth`, `max_operations` ou `max_conclusions`. A API não apresenta uma lista parcial como conclusão completa.

A implementação não resolve automaticamente conflitos entre fatos incompatíveis, não inventa proveniência, não assume que frequência de acesso seja relevância semântica e não executa regras recursivas sem proteção contra duplicação e limites.

## 5. Atualizações incrementais

O `DependencyTracker` constrói um índice reverso a partir das trilhas existentes. Quando um fato explícito é removido, a invalidação percorre somente os dependentes alcançáveis no grafo de provas. Conclusões fora dessa região são preservadas. Se uma conclusão tiver provas alternativas, a sessão marca o estado como incompleto e exige `recompute()` antes de declarar o conjunto final exato.

Uma adição de fato também marca a sessão como `stale`, porque o motor atual não possui uma agenda incremental completa para descobrir todos os novos joins habilitados. Portanto, esta versão demonstra **invalidação incremental segura**, mas não declara atualização incremental total para inserções. Essa limitação é intencional e está coberta por testes.

## 6. Validação quantitativa

O benchmark foi executado com `python3 phase7_bench.py --out results/phase7/knowledge_benchmark --seeds 30`. Cada cenário usou 15 seeds de calibração e 15 seeds holdout; os registros foram mantidos em `runs.csv`. A medição mistura dois cenários controlados, portanto `n=30` por método representa os dois cenários combinados, não 30 datasets independentes.

| Método no holdout | Latência mediana | P95 observado | Fatos/conclusões examinados | Observação |
|---|---:|---:|---:|---|
| Inferência completa | 185,888 ms | 246,811 ms | 288.118 | estado completo quando não excede limites |
| Lookup de conclusão em cache | 1,017 ms | 2,553 ms | 0 | reutiliza conclusões já produzidas |
| Explicação | 0,262 ms | 0,508 ms | 2,5 | custo de trilha curta neste fixture |
| Invalidação localizada | 0,043 ms | 0,057 ms | 18,5 | 17,5 conclusões invalidadas; estado requer recomputação quando há ambiguidade |

A comparação não autoriza dizer que a invalidação é “mais rápida que inferência” como uma tarefa equivalente: ela não produz novamente todas as conclusões. O resultado mensurado é que a manutenção localizada visita uma região muito menor, ao custo de exigir recomputação quando a correção final não pode ser provada localmente.

A calibração teve inferência completa de 180,503 ms, lookup de 0,862 ms, explicação de 0,299 ms e invalidação de 0,043 ms. O holdout teve valores próximos, sem mudança adaptativa treinada artificialmente. O gráfico e os dados brutos estão em `results/phase7/knowledge_benchmark/`.

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
| Alterações invalidam conclusões afetadas | Atendido para invalidação localizada; inserções e provas alternativas exigem recomputação |
| Proteção contra ciclos/explosão | Atendido por deduplicação e limites configuráveis |
| Testes independentes | Atendido: 101 testes combinados passaram |
| Custo computacional documentado | Atendido no benchmark sintético de 30 seeds e duas famílias |
| Benchmarks reproduzíveis | Atendido para o benchmark sintético; SNAP semântico ainda não integrado |
| Resultados históricos preservados | Atendido; nenhum artefato das Fases 1–6 foi sobrescrito |
| Rust atualizado/integrado | Não atendido nesta etapa; ainda sem justificativa quantitativa end-to-end |
| Forward/backward/híbrido comparados | Parcial: forward e backward implementados e testados, mas ainda sem comparação quantitativa dedicada; híbrido não implementado |
| Holdout com controlador adaptativo de estratégia | Não atendido; controlador permanece o da Fase 6 e não foi promovido |
| Dataset público com transformação semântica auditável | Não atendido; SNAP continua estrutural, não semântico |

**Veredito:** a fundação estruturada da Fase 7 é funcional e validada em testes e benchmark controlado, mas a Fase 7 completa ainda não está concluída. As próximas prioridades são implementar e comparar backward/híbrido, ampliar atualização incremental para inserções com agenda de deltas, adicionar benchmark real apenas quando houver mapeamento semântico defensável, e avaliar Rust end-to-end somente após medir o custo da proveniência.

## 10. Artefatos e reprodução

```bash
cd Aether
python3 -m unittest discover -v
python3 phase7_bench.py --out results/phase7/knowledge_benchmark --seeds 30
```

Artefatos principais:

- `phase7_bench.py`
- `results/phase7/knowledge_benchmark/runs.csv`
- `results/phase7/knowledge_benchmark/summary.json`
- `results/phase7/knowledge_benchmark/provenance.json`
- `results/phase7/knowledge_benchmark/phase7_knowledge_benchmark.png`
- `PHASE7_AUDIT.md`
