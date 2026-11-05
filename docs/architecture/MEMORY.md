# Memória e persistência

## Memória operacional em camadas

`AdaptiveMemory` guarda payloads bytes opacos. Frequência e recência determinam a promoção para `warm`/`hot` e a preferência de eviction; o mecanismo não transforma frequência em verdade semântica. `max_bytes` limita o tamanho dos payloads residentes (não é uma medição exata de RSS nem inclui o overhead do runtime Python).

Com `cold_store` configurado, o cold tier usa SQLite, transações, `synchronous=FULL` e verificação SHA-256 do payload recuperado. Cada `put` é persistido antes da alteração residente; `delete` é durável; substituições não ressuscitam valores antigos após reinício. `compact()` solicita checkpoint do WAL, `VACUUM` e `integrity_check`. Um arquivo JSONL legado é validado e migrado para SQLite por substituição atômica; uma linha final incompleta é ignorada, enquanto registros completos com hash inválido bloqueiam a migração.

```python
from aether.memory.adaptive_storage import AdaptiveMemory

with AdaptiveMemory(64 * 1024, cold_store="~/.cache/aether/memory.sqlite3") as memory:
    memory.put("query:sent_email_to", b"opaque operational payload")
    payload = memory.get("query:sent_email_to")
```

A conexão SQLite serializa gravações no arquivo, mas o cache residente e suas estatísticas em RAM são por instância. O orçamento é por payload bytes, não um limite de RSS completo. Fechar e reabrir a instância recupera o cold tier; estatísticas transitórias de hits/misses começam de novo.

## Persistência do conhecimento

`KnowledgeStore.save(path)` grava um snapshot JSON com schema versionado, checksum SHA-256, escalares tipados e serialização IEEE-754 em bytes para preservar `bool`/`int`/`float`, signed zero e payloads de NaN. O arquivo temporário é gravado e sincronizado no mesmo diretório antes de `os.replace`. `KnowledgeStore.load(path)` valida o envelope, checksum, schema, índices e IDs e devolve um store novo; uma falha não altera uma instância ativa.

Os snapshots preservam entidades, fatos, propriedades, IDs, proveniências e confiança por evidência, versões total/estrutural e o histórico retido. `history_limit` é configurável (padrão 10.000); ao exceder o limite, os registros mais antigos são descartados e `history_stats()` informa `truncated_through`. `history_changes(offset, limit)` retorna páginas sobre o histórico ainda retido.

```python
from aether.core.knowledge.store import KnowledgeStore

store = KnowledgeStore(history_limit=20_000)
store.save("data/aether-knowledge.json")
restored = KnowledgeStore.load("data/aether-knowledge.json")
```

O snapshot é um ponto de recuperação, não um log transacional de cada write. Coordenar snapshot de conhecimento com eventos de domínio requer o Event Engine e a política de checkpoints correspondentes; não se assume atomicidade cruzada entre dois arquivos ou dois bancos.

## Padrões operacionais limitados

`IncrementalPatternLearner` agora limita globalmente chaves (`max_keys`, padrão 4.096), tipos de operação (`max_kinds`, 64), fontes de transição (`max_transition_sources`, 4.096) e alvos por fonte (`max_transition_targets`, 64). Ao exceder o conjunto residente, remove o contador menos frequente com desempate lexical determinístico e registra evicções. `events_seen` permanece a contagem observada total; a frequência de uma entrada descartada deixa de ser retida. O custo de substituição pode examinar o conjunto limitado, portanto não se promete O(1) quando há eviction.

Os padrões contam acessos/transições, não semântica. Contadores, cache, histórico de consultas, log de eventos e conhecimento explícito continuam distintos. Benchmarks de manutenção/recuperação estão em [OPERATIONAL_BENCHMARKS](OPERATIONAL_BENCHMARKS.md).
