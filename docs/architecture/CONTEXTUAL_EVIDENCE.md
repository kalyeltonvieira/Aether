# Contexto por evidência (primeiro incremento da Etapa 2)

## Escopo

Este incremento adiciona rótulos contextuais a cada registro de evidência de um fato e permite selecionar evidências antes da inferência. É uma primeira fatia de recuperação contextual — **não** implementa ainda memória episódica, aprendizagem de estruturas ou contexto inferido automaticamente. Retração seletiva de evidências e ledger de revisão de conflitos estão descritos em [EVIDENCE_REVIEW.md](EVIDENCE_REVIEW.md).

O contexto é um mapa de até 32 pares `string → string`; cada chave tem até 64 caracteres e cada valor até 256. Chaves e valores devem ser não vazios. A comparação é exata. Exemplos de rótulos são `domain`, `period`, `project` e `source_scope`; esses nomes não têm semântica embutida no core.

## Modelo e escrita

O contexto pertence a `FactEvidence`, não à identidade do fato. Portanto, duas fontes podem apoiar a mesma relação com contextos diferentes sem criar duas identidades relacionais distintas; cada evidência mantém sua própria proveniência, confiança e contexto.

A API de fatos aceita contexto na criação e atualização:

```json
{
  "subject": "alice",
  "predicate": "role",
  "object": "analyst",
  "object_type": "str",
  "provenance": {"source": "directory"},
  "context": {"domain": "hr", "period": "2026"}
}
```

`GET /facts` expõe o contexto em cada elemento de `evidence_records`. O patch de `context` atualiza a evidência principal e preserva as demais evidências existentes na substituição.

## Seleção e inferência

`POST /queries` e `POST /explanations` aceitam `context_filter`. Um filtro não vazio seleciona uma evidência somente se **um mesmo registro** contiver todos os pares solicitados com igualdade exata. Depois, o raciocínio recebe uma visão contendo somente os fatos que ainda têm evidência correspondente; assim, uma regra não pode combinar um antecedente de `hr` com outro sustentado apenas por `security`.

A seleção ocorre antes de `forward`, `backward`, `hybrid` ou `adaptive`. Consultas sem filtro continuam vendo todo o store e mantêm o comportamento anterior. As respostas contextualizadas incluem o `context_filter` efetivamente aplicado e `context_fact_count`, a quantidade de fatos elegíveis antes da inferência. O filtro faz parte da chave do cache. Links do Reasoning Console para o Proof Explorer carregam o mesmo filtro.

### Exemplo

```json
{
  "subject": "alice",
  "predicate": "role",
  "object": "?role",
  "strategy": "forward",
  "context_filter": {"domain": "hr"}
}
```

Fatos legados e evidências sem rótulos não são elegíveis para um filtro contextual não vazio. Para consultá-los, omita `context_filter` ou envie `{}`.

## Persistência e compatibilidade

O formato de snapshot passou a schema v2 para armazenar contextos por evidência; o ledger de resolução começou em v3 e sua invalidação monotônica evolui o formato atual para schema v4. O loader aceita schema v1 (contexto vazio), v2 (contexto preservado, ledger vazio), v3 (ledger mantido como histórico inválido) e v4. A assinatura/checksum e as verificações estruturais continuam aplicadas. Novos snapshots são sempre escritos em v4.

## Limites importantes

- Rótulos são metadados declarados pelo produtor, não uma interpretação ou verdade inferida pelo AETHER.
- Um filtro sem resultados significa que não há evidência elegível naquele recorte; não refuta a relação fora dele.
- O contexto **não é autorização nem isolamento de segurança**. As rotas continuam dependendo de sessão, papel e CSRF; não use o campo para proteger dados de tenants.
- Regras não geram nem propagam automaticamente contextos para fatos derivados. Elas apenas raciocinam sobre o conjunto pré-selecionado.
- O filtro é uma correspondência simples de pares exatos; não há hierarquia, janela temporal, pontuação de relevância, fallback semântico ou seleção probabilística. Conflitos só são detectados se o chamador declarar uma regra de incompatibilidade; não há detector semântico automático.
- A visão contextual é materializada por consulta após um cache miss; medição e otimização desse custo pertencem à Etapa 3.

A especificação geral da API está em [API.md](API.md); o roadmap de implementação está em [plan.md](../../plan.md).
