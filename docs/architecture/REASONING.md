# Conhecimento e raciocínio

## Estado explícito

`KnowledgeStore` é o armazenamento canônico de entidades e fatos explícitos. Um fato é identificado por `(subject, predicate, object tipado)`; `bool`, `int`, `float64`, `str` e `None` permanecem distintos. Objetos e propriedades aceitam escalares, não estruturas arbitrárias. Os índices por sujeito, predicado e objeto são mantidos pelo próprio store.

Cada fato conserva um `fact_id` estável durante a vida do store e registros de evidência (`FactEvidence`). Repetir uma afirmação com outra proveniência ou confiança não cria um segundo fato nem descarta silenciosamente a nova evidência: ela é anexada ao registro existente. `Fact.provenance` e `Fact.confidence` continuam expondo o primeiro registro para compatibilidade; `Fact.provenances`, `Fact.confidence_values` e `Fact.evidence_records` expõem as evidências acumuladas. Propriedades complementares são unidas; um valor conflitante para a mesma propriedade é rejeitado explicitamente.

As evidências e a confiança declarada não são probabilidades calibradas. A ausência de proveniência pode ser compensada por uma evidência posterior, mas conflitos semânticos não são resolvidos automaticamente.

## Inferência e provas

`InferenceEngine.infer()` executa forward chaining por profundidade, e `BackwardInference` oferece busca dirigida para metas fechadas. `HybridInference` combina as duas estratégias. O caminho forward agrega várias provas independentes para a mesma conclusão; cada prova mantém regra, revisão, profundidade e suportes. `DependencyTracker` invalida suportes por prova e preserva uma conclusão enquanto restar outra prova válida.

`InferenceEngine.explain_all()` percorre as provas alternativas e evidencia as proveniências de cada fato explícito de suporte. O campo legado `ExplanationNode.provenance` permanece disponível; `provenances` contém todas as fontes. Avaliações de consistência distinguem conhecimento explícito, derivado, desconhecido, contradito e evidência insuficiente.

## Consultas abertas e paginação

Uma consulta é expressa por `Pattern`, por exemplo:

```python
from aether.reasoning.inference import InferenceEngine, Pattern

page = InferenceEngine(store).query(
    Pattern("?x", "sent_email_to", "?y"),
    max_results=100,
    offset=0,
)
```

`QueryResult.solutions` contém bindings tipados, chave do fato, identificador explícito quando aplicável, provas e explicação. A ordem é determinística para um estado imutável do store. Ao existir outra solução além da página, `complete` é `False`, `stop_reason` é `"max_results"` e `next_offset` informa o deslocamento para a página seguinte. Se o limite computacional da inferência for atingido, o motivo do limite é preservado e a resposta permanece incompleta; ausência de solução em resultado incompleto não equivale a negação.

Offsets são páginas por deslocamento, não cursores vinculados criptograficamente a uma versão. Para resultados reproduzíveis, não altere o store entre páginas; depois de uma mutação, reinicie a paginação. `InferenceLimits` mantém limites independentes de profundidade, operações e conclusões.

## Limites conhecidos

O core é relacional e simbólico, não uma interface de linguagem natural. `KnowledgeStore` ainda é em memória; persistência semântica, histórico durável de alterações e sincronização transacional com o Event Engine permanecem tarefas separadas. O backward chaining retorna uma prova singular; a coleção completa de provas alternativas é garantida no resultado forward e nas explicações derivadas desse resultado. A API pública do Studio deverá expor completude e limites, sem converter truncamento em resultado completo.
