# Event Engine

`aether.temporal.engine.EventEngine` é uma fila ordenada e um log durável SQLite para envelopes JSON tipados. Cada evento registra ID, sequência de ingestão, timestamp declarado, tipo, origem, payload, proveniência, estado, tentativas e erro recente. Payload e proveniência são validados como JSON finito; o tamanho total é limitado por `max_payload_bytes`. O banco usa WAL, `synchronous=FULL`, schema versionado e `integrity_check` na abertura.

## Ordem e deduplicação

A sequência SQLite é a ordem autoritativa de ingestão e processamento. Timestamps são metadados de ocorrência e podem chegar fora de ordem; a consulta temporal filtra pelo timestamp, mas o replay continua usando sequência de ingestão. Reutilizar `event_id` com o mesmo envelope é idempotente e retorna o evento existente; reutilizá-lo com payload/origem/tipo diferentes é rejeitado. Quando o timestamp não foi fornecido pelo cliente, retries com o mesmo `event_id` e mesmo conteúdo reaproveitam o timestamp originalmente aceito.

O processador preserva FIFO para um banco: um evento com falha terminal bloqueia os seguintes até ser re-enfileirado explicitamente. O claim é transacional e usa lease; `recover_interrupted()` libera leases expirados. `max_pending` aplica backpressure, contando pending, processing e failed; duplicatas já aceitas continuam respondendo mesmo com a fila cheia.

## Garantia de entrega

A garantia é **at-least-once**, não exactly-once. Se o processo cair depois de o handler aplicar um efeito e antes de confirmar `processed`, o mesmo evento pode ser entregue outra vez depois de expirar o lease. Handlers devem ser idempotentes usando `event_id`; o Event Engine não abre uma transação distribuída com bancos ou side effects externos. Erros são registrados com tipo/mensagem truncada; tentativas usam retry delay exponencial. Depois de `max_attempts`, o evento fica `failed` e requer `requeue(event_id)`.

Embora múltiplos produtores e consumidores possam disputar o banco com claims SQLite, o stream é deliberadamente de **um evento ativo por vez** para preservar a ordem global. O processamento de eventos diferentes não é paralelizado por esta implementação. Aumentar throughput com partições exige uma definição explícita de chave de ordenação e não deve remover o FIFO por acidente.

## Histórico, replay e checkpoints

`events(after_sequence, limit, ...)` oferece paginação por sequência, filtros de tipo/estado/timestamp e retorna `next_after`. `replay(handler, after_sequence, through_sequence)` percorre eventos já processados em sequência e não altera seus estados; o handler de replay também deve ser idempotente ou construir um estado descartável.

`save_checkpoint(bytes, sequence=...)` grava estado opaco limitado pelo orçamento de payload, com SHA-256. `load_checkpoint()` verifica integridade, e `compare_checkpoints()` compara hash e sequência. A aplicação é responsável por serializar/deserializar o estado do domínio; o Event Engine não interpreta bytes de checkpoint.

```python
from aether.temporal.engine import EventEngine

with EventEngine("data/aether-events.sqlite3", max_pending=5000) as events:
    receipt = events.enqueue(
        "fact.add", {"subject": "alice", "predicate": "sent_email_to", "object": "bob"},
        source="studio", event_id="client-request-42",
    )
    result = events.process_batch(handle_event, limit=100)
```

`KnowledgeEventProcessor` integra `entity.add`, `entity.update`, `fact.add` e `fact.remove` ao `KnowledgeReasoner`. Fatos adicionados pelo handler propagam-se por inferência incremental quando o reasoner possui estado completo. Remoções usam o rastreador de dependências e deixam o estado explicitamente incompleto até recomputar; um replay seguro não pode apresentar uma conclusão antiga como atual. Se `snapshot_path` estiver configurado, o store é salvo atomicamente antes de o handler retornar. O reenvio de `fact.add` com o mesmo evento/proveniência não duplica evidências; remoção repetida é no-op. A fila e o snapshot continuam sendo transações distintas, então a garantia permanece at-least-once.

`TemporalEdgeHistory` e `SelectiveCheckpointHistory` continuam disponíveis para workloads compactos de grafos em memória. A validação de integração exercita adicionar fato, propagar uma conclusão, remover o suporte, recomputar e comparar com o oráculo completo.
