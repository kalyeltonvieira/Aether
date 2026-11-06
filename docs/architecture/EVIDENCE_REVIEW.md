# Retração de evidências e revisão de conflitos

## Escopo

Esta fatia implementa duas operações do núcleo: retirar uma fonte específica que sustenta um fato e registrar uma decisão humana sobre um conjunto de fatos em conflito. Ela não escolhe automaticamente qual afirmação é verdadeira e não altera a regra de inferência para ocultar dados contraditórios.

## Retirada seletiva

Cada `FactEvidence` expõe `evidence_id`, um identificador determinístico derivado dos campos de proveniência, confiança e contexto. O identificador permite selecionar um registro exato sem depender da posição mutável da evidência na lista. Ele identifica o registro; não é uma nota de confiança nem uma avaliação de veracidade.

`KnowledgeStore.remove_evidence(fact_id, evidence_id)` tem dois resultados possíveis:

- Se ainda houver outra evidência, o fato conserva o mesmo `fact_id` e a mesma relação lógica. A retirada aparece no histórico como `fact_evidence_removed`; `structural_version` não muda.
- Se era a última evidência, o fato inteiro é retirado dos índices e a alteração é registrada como `fact_removed`.

`KnowledgeReasoner.remove_evidence()` mantém atuais as conclusões quando o fato continua apoiado por outra evidência. Ao retirar a última, usa a invalidação por suporte de `DependencyTracker`: invalida conclusões sem prova alternativa, preserva as que ainda têm uma prova independente e marca o resultado como incompleto até uma recomputação completa. A existência de uma conclusão parcial após invalidação não deve ser interpretada como prova completa.

```python
fact = store.query(subject="alice", predicate="employed_by")[0]
source_id = fact.evidence_records[0].evidence_id
result = reasoner.remove_evidence(fact.fact_id, source_id)
```

O `EvidenceRetractionResult` retorna a evidência retirada, o fato remanescente (ou `None` quando o fato foi removido), estatísticas de invalidação quando aplicáveis e o estado de completude da inferência.

## Revisão de conflito

Conflitos continuam sendo declarados pelo chamador por meio de `IncompatibilityRule`; o núcleo não presume que predicados ou valores diferentes sejam contraditórios. `ConsistencyValidator.assess()` detecta o conflito e retorna `CONTRADICTED`, sem escolher um vencedor.

`ConsistencyValidator.record_resolution(fact_ids, selected_fact_ids, reason=..., resolved_by=...)` registra uma decisão humana separada. A revisão contém os fatos envolvidos, o subconjunto selecionado, motivo, revisor, instante e fingerprint do conjunto de evidências desses fatos. Ela é armazenada no próprio `KnowledgeStore` e incluída em snapshots schema v4.

A revisão não apaga nem reescreve fatos e não modifica os resultados da inferência. Enquanto as evidências e os IDs envolvidos permanecerem iguais e a revisão não tiver sido invalidada, `assess()` anexa a revisão à avaliação — mas mantém o status `CONTRADICTED`, deixando visível que os registros originais seguem em conflito. Se evidência for adicionada ou retirada, a revisão corrente é invalidada de modo monotônico; mesmo que o conjunto de evidências volte ao estado anterior, a decisão precisa ser revista. Registros antigos permanecem no ledger para auditoria.

```python
assessment = validator.assess(claim, incompatibilities=(rule,))
resolution = validator.record_resolution(
    assessment.explicit_fact_ids + assessment.conflicting_fact_ids,
    (chosen_fact_id,),
    reason="revisão documental concluída",
    resolved_by="operador-42",
)
```

## Exposição REST e Studio

O Studio expõe `evidence_id` na representação de cada evidência. `DELETE /api/v1/facts/{fact_id}/evidence/{evidence_id}` exige sessão de operador e CSRF, usa o `KnowledgeReasoner` sob o lock do estado, persiste a mudança, limpa cache, mantém o fato se houver outra fonte e retorna as estatísticas de invalidação. IDs malformados retornam 422; evidência/fato válido mas inexistente retorna 404. A atividade entra no histórico do store e é publicada como `knowledge.changed`.

`POST /api/v1/consistency/assessments` retorna o status do claim, completude, suficiência de proveniência, fatos conflitantes, provas derivadas e revisão vigente. A aplicação fornece as regras de incompatibilidade explicitamente. `POST /api/v1/consistency/resolutions` exige operador/CSRF e reavalia, sob o lock do estado, que o conflito ainda existe, que a evidência é suficiente e que os IDs selecionados fazem parte daquele conflito; o ator é tomado da sessão autorizada. A revisão é persistida e notificada por `consistency.changed`. `GET /api/v1/consistency/resolutions` lista o ledger, incluindo decisões invalidadas. A tela Knowledge Explorer permite remover suporte individual; Reasoning Console permite avaliar status, selecionar os IDs aceitos e registrar a justificativa.

O assessment e o ledger de revisão REST são globais ao store neste incremento. Revisões condicionadas a `context_filter`, políticas de autoridade entre fontes e inferência contextual automática de incompatibilidades ainda não existem; continuam explícitas e não são inferidas a partir de linguagem natural.

## Compatibilidade e limites

- Snapshots novos usam schema v4. Snapshots v1 carregam evidências com contexto vazio; snapshots v2 preservam o contexto e inicializam o ledger vazio; snapshots v3 preservam as revisões como histórico invalidadas, exigindo revalidação explícita, pois não registravam invalidação monotônica.
- O fingerprint depende dos IDs estáveis dos registros de evidência. Confiança continua sendo metadado declarado, não probabilidade calibrada.
- Uma revisão não valida por si só que a regra de incompatibilidade é correta; regras e seleção continuam decisões explícitas da aplicação/revisor.
- Descoberta automática de conflito, resolução probabilística e política de autoridade das fontes continuam fora desta fatia. A revisão registrada é auditável, mas não constitui prova de veracidade nem altera o status contradito.

Veja também [Conhecimento e raciocínio](REASONING.md) e [Contexto por evidência](CONTEXTUAL_EVIDENCE.md).
