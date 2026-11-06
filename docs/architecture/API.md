# API do AETHER Studio

Este documento descreve a API opcional do Studio implementada em `aether.interfaces.api`. A API compõe o `KnowledgeStore`, `KnowledgeReasoner`, `AdaptiveMemory` e `EventEngine` reais; não há respostas sintéticas no backend. A base HTTP é `/api/v1` e o WebSocket de notificações é `/ws`.

## Instalação e execução

Instale a camada opcional:

```bash
python -m pip install -e ".[api]"
```

O entrypoint suporta os flags usados pelo launcher local:

```bash
python -m aether.interfaces.api \
  --host 127.0.0.1 \
  --port 8000 \
  --data-dir .aether-data \
  --auth-mode token \
  --public-origin http://localhost:3000 \
  --seed-fixture
```

`--seed-fixture` é exclusivamente para dados de teste e só grava quando o store está vazio. O valor de `--data-dir` é um diretório de dados local escolhido pelo administrador; não existe endpoint que aceite paths ou código executável.

Para Uvicorn, use a factory para evitar criar banco, memória e sessões durante um import:

```bash
uvicorn aether.interfaces.api.app:create_app --factory \
  --host 127.0.0.1 --port 8000
```

A execução suportada é um worker por diretório de dados. Não execute múltiplos processos compartilhando o mesmo snapshot e os mesmos bancos SQLite.

## Autenticação e autorização

Todas as rotas, exceto `/health` e `/api/v1/auth/info`, exigem sessão. Leituras exigem sessão autenticada. Mutações exigem sessão com papel `operator` e o header `X-CSRF-Token` igual ao token CSRF retornado no login/sessão. O token de operador nunca é retornado pela API.

### Manus OAuth e Preview gerenciado

O padrão é `--auth-mode manus` (ou `AETHER_AUTH_MODE=manus`). No modo gerenciado, a sessão usa o cookie `HttpOnly` **`webdev_app_session`**, o nome esperado pelo ambiente Preview. O servidor trata um valor conhecido de sessão opaca como sessão emitida por ele; um valor desconhecido no mesmo cookie é aceito somente quando for um JWT HS256 válido com:

- `MANUS_JWT_SECRET` configurado no servidor;
- `exp` presente e ainda válido;
- `appId` (ou alias de projeto suportado) exatamente igual a `MANUS_PROJECT_ID` ou `MANUS_APP_ID`;
- `openId`, `open_id` ou `sub` presente.

A primeira requisição válida que traz o JWT recebe uma sessão opaca no mesmo cookie. JWT ausente, expirado, malformado, sem projeto ou de outro projeto não autentica. O papel padrão é `reader`. O papel `operator` só é atribuído se o identificador estiver explicitamente em `AETHER_OPERATOR_OPEN_IDS` (lista separada por vírgulas); aliases de owner configurados no servidor também podem compor essa allowlist. Identidade Preview, por si só, nunca concede escrita.

`GET /api/v1/auth/login-url` compõe `$MANUS_OAUTH_PORTAL_URL/app-auth` com `appId=MANUS_PROJECT_ID`, `redirectUri`, `responseType=code` e `state` contendo JSON base64 com `redirectUri` + `nonce`; state de uso único também é ligado a cookie HttpOnly curto. `GET /api/v1/auth/callback` valida cookie/state, faz POST de JSON server-side a `$MANUS_OAUTH_API_URL/webdev.v1.WebDevAuthPublicService/ExchangeToken` e depois `GetUserInfo`, cria sessão com `openId` e redireciona ao `/` fixo. Código e access token nunca passam à UI. O protocolo é coberto com provider HTTP simulado; o login contra o provedor Manus real requer autenticação por navegador e não foi declarado testado se não for concluído.

Em Preview HTTPS explicitamente configurado com `--public-origin https://...`, o cookie de sessão usa `Secure; SameSite=None`. Em HTTP local usa `SameSite=Strict` e não usa `Secure`.

### Token independente

O modo token só é habilitado explicitamente com `--auth-mode token` ou `AETHER_AUTH_MODE=token`, destinado a instalação independente, CLI e testes. O valor vem de `AETHER_OPERATOR_TOKEN` ou de um arquivo privado `operator-token` gerado com permissão restrita no diretório de dados. O valor é trocado por uma sessão opaca no cookie **`aether_studio_session`** e não permanece no frontend.

O CLI recusa modo token em um host não-loopback sem `AETHER_OPERATOR_TOKEN`. Em loopback, pode gerar o arquivo privado; apenas o caminho é registrado em log, nunca o segredo. O login por token não está disponível no modo Manus.

### Endpoints de autenticação

| Método e rota | Acesso | Resultado |
|---|---|---|
| `GET /health` | público | `{status:"ok"}` mínimo |
| `GET /api/v1/auth/info` | público | `{mode,login_available}` sem segredo |
| `GET /api/v1/auth/login-url` | Manus | `{url}` e cookie de state |
| `GET /api/v1/auth/callback?code=&state=` | Manus | cria sessão e retorna sessão |
| `POST /api/v1/auth/login` | token | recebe `{token}`; cria sessão |
| `GET /api/v1/auth/session` | sessão | papel, CSRF e modo atuais |
| `POST /api/v1/auth/logout` | sessão + CSRF | revoga sessão e limpa cookie |

Exemplo de login independente:

```bash
login=$(curl -si -c cookies.txt -H 'Content-Type: application/json' \
  -d '{"token":"<valor-fornecido-ao-administrador>"}' \
  http://127.0.0.1:8000/api/v1/auth/login)
# O cliente extrai csrf_token da resposta e o usa somente no header.
```

Não coloque token, CSRF ou qualquer segredo em `localStorage`/`sessionStorage`.

## Conhecimento e páginas

Todas as páginas usam o formato:

```json
{"items": [], "total": 0, "offset": 0, "limit": 100, "next_offset": null}
```

`GET /api/v1/entities?search=&offset=0&limit=100` lista entidades; `GET /entities/{entity_id}` lê uma entidade; `POST /entities` recebe `{entity_id,properties}`; `PATCH /entities/{entity_id}` recebe `{properties}`. Os dois últimos são mutações de operador.

`GET /api/v1/facts?subject=&predicate=&offset=0&limit=100` lista fatos. Cada fato inclui `fact_id`, sujeito, predicado, objeto escalar bruto, `object_type`, propriedades, confiança, `provenances` e `evidence_records` (cada evidência carrega `evidence_id`, proveniência, confiança e `context`). O ID estável é derivado do conteúdo do registro, não de sua posição. Os objetos preservam `bool`, `int`, `float`, `str` e `null` como identidades distintas. `POST /facts` aceita:

```json
{
  "subject": "alice",
  "predicate": "sent_email_to",
  "object": "bob",
  "object_type": "str",
  "properties": {},
  "confidence": 0.9,
  "provenance": {"source": "mail-import", "evidence_type": "message"},
  "context": {"domain": "communications", "period": "2026"}
}
```

`context` aceita até 32 pares de strings (chaves até 64 caracteres, valores até 256). O contexto é por evidência, não parte da identidade relacional. `PATCH /facts/{fact_id}` valida uma substituição. Se sujeito, predicado ou objeto mudarem, a resposta informa `replaced_fact_id`, `new_fact_id` e `key_changed`; evidências anteriores são carregadas para a nova chave. `DELETE /facts/{fact_id}` remove o fato e retorna o registro removido. `DELETE /facts/{fact_id}/evidence/{evidence_id}` retira apenas a evidência indicada; o fato permanece se outra fonte ainda o sustentar e é removido apenas quando a última evidência sai. A operação exige operador e `X-CSRF-Token`, persiste a mudança, invalida cache, registra histórico e emite `knowledge.changed`.

`GET /history` retorna mudanças reais do store com sequência, timestamp, operação, versões e snapshots `before`/`after`. O histórico está sujeito ao limite de retenção do `KnowledgeStore`.

`GET /graph?predicate=&center=&offset=0&limit=250` projeta relações entre entidades existentes. Apenas objetos string que também são IDs de entidades viram nós; o filtro `center` retorna sua vizinhança observada antes da paginação. A resposta preserva `{nodes,edges,truncated}` e inclui `{total,offset,limit,next_offset}`. As arestas são ordenadas de forma estável por `fact_id`; `next_offset` é `null` na última página.

`GET /rules` lista regras. `POST /rules` recebe `rule_id`, `antecedents`, `consequent`, `revision` opcional e `enabled`; `DELETE /rules/{rule_id}` remove uma regra. Padrões são dados estruturados, não expressões Python.

## Consultas, inferência e provas

`POST /api/v1/queries` recebe sujeito, predicado, objeto, `strategy` opcional (`forward`, `backward`, `hybrid` ou `adaptive`), `offset`, `limit` e `context_filter` opcional. Quando omitida, `strategy` usa `default_strategy` da configuração; `adaptive` continua disponível somente como estratégia explícita de consulta. Cada solução inclui `object_type`, e cada nó da árvore `explanation` inclui `key_type` com os tipos escalares de `[subject,predicate,object]`, preservando links recursivos para objetos `int` e `float`. A resposta expõe soluções e metadados do motor real:

```json
{
  "solutions": [],
  "proven": false,
  "complete": true,
  "stop_reason": null,
  "next_offset": null,
  "operations": 0,
  "facts_examined": 0,
  "conclusions_produced": 0,
  "strategy": "forward",
  "decision_ns": 0,
  "execution_ns": 0,
  "rationale": "explicit_forward_query"
}
```

Consultas abertas usam `forward` ou `adaptive`. Metas abertas em `backward`/`hybrid` são rejeitadas com erro útil; essas estratégias são dirigidas a metas fechadas. `complete:false` nunca é convertido em uma negativa semântica. O padrão é `forward`: medições da decisão adaptativa não justificam pagar seu overhead em toda consulta.

Um `context_filter` não vazio seleciona fatos quando **uma mesma evidência** contém todos os pares solicitados com igualdade exata. A seleção antecede todas as estratégias de inferência, evitando joins entre fatos elegíveis em contextos distintos. Fatos/evidências antigos sem contexto permanecem disponíveis sem filtro, mas não correspondem a um filtro não vazio. Respostas contextualizadas incluem `context_filter` e `context_fact_count`; o filtro integra a identidade da entrada de cache e é preservado nos links do Proof Explorer. Esse campo é metadado de recuperação, não controle de acesso. Consulte [Contexto por evidência](CONTEXTUAL_EVIDENCE.md) para limites e exemplos.

`POST /inference` recomputa o fechamento real e é mutação de operador. `POST /explanations` recebe uma chave e o mesmo `context_filter` opcional, e retorna provas alternativas, regra/revisão, depth, suportes, fato explícito e proveniência; nós da árvore também incluem `key_type`. O backend não inventa soluções quando o motor não prova a chave no conjunto selecionado.

`POST /api/v1/consistency/assessments` recebe um claim concreto (`subject`, `predicate`, `object`, `object_type?`) e `incompatibilities`, uma lista explícita de relações entre predicados (`predicate_a`, `predicate_b`, opcionalmente `object_pairs`). O resultado separa `explicit`, `derived`, `unknown`, `contradicted` e `insufficient_evidence`, inclui IDs de fatos, `evidence_sufficient`, `complete`, provas, revisão vigente e uma nota. Incompatibilidades não são adivinhadas; a avaliação é global sobre o store. Uma conclusão ausente nunca vira falso, e uma avaliação com evidência ausente/inferência incompleta é explicitamente insuficiente.

`POST /api/v1/consistency/resolutions` recebe o mesmo claim e incompatibilidades, mais `selected_fact_ids` e `reason`. É mutação exclusiva de operador com CSRF; o servidor reavalia o conflito, exige status contradito e proveniência suficiente, confere que os IDs selecionados pertencem ao conflito atual e grava o ator da sessão (não um valor livre do browser). A resposta inclui a avaliação atualizada, que continua `contradicted`: revisão humana é auditável, não sobrescreve evidência nem declara verdade automática. `GET /api/v1/consistency/resolutions` retorna o ledger completo, incluindo revisões invalidadas. Evidência nova/retirada invalida a revisão por fingerprint. Resolução por contexto ainda não é suportada; consultas contextuais continuam disponíveis em `/queries` e `/explanations`.

## Memória, configuração e métricas

`GET /memory` expõe estatísticas reais da `AdaptiveMemory`, cache de consultas limitado, padrões operacionais limitados e indicação de cold tier persistente. Não expõe payloads arbitrários do cache. `PUT /memory/budget` recebe `{max_bytes}` e altera o orçamento residente sem apagar o cold store. Com persistência desativada no startup, o cold tier não abre SQLite, `persistent` é falso e dados evictados não são recuperáveis após encerramento.

`GET /config` retorna:

```json
{
  "memory_max_bytes": 8388608,
  "max_depth": 8,
  "max_operations": 10000,
  "max_conclusions": 1000,
  "default_strategy": "forward",
  "join_planner": "input",
  "persistence_enabled": true,
  "rust_enabled": false,
  "event_batch_size": 100
}
```

`PUT /config` aceita esses campos com limites. `default_strategy` aceita somente `forward`, `backward` ou `hybrid`; `adaptive` deve ser enviado explicitamente em cada consulta. `persistence_enabled` é startup-only: alterá-lo via API retorna 422, pois os handles SQLite e os componentes de memória são escolhidos ao criar o estado. Para mudar o modo, edite `config.json` no diretório de dados com o Studio encerrado (por padrão, `.aether-data/config.json`) e reinicie. Quando falso, conhecimento/regras não são carregados nem gravados, a fila de eventos usa SQLite `:memory:` e a memória não tem cold store em disco. `config.json` continua sendo escrito para preservar o modo escolhido; arquivos de dados anteriores não são removidos e ficam ignorados até a persistência ser reativada. Apague-os manualmente apenas se a intenção for eliminar os dados antigos. Paths e segredos não são configuráveis via API. `rust_enabled:true` só é aceito quando a biblioteca nativa foi realmente localizada e carregada; a API não compila nem presume Rust durante o status. `join_planner=input` é o padrão medido; `selective` é opt-in.

`GET /metrics?period=60` retorna amostras observadas em ring buffer, sem preencher histórico vazio com dados fabricados. CPU/RSS podem ser `null` quando o host não disponibiliza a medida; `rust_operations` também é `null` enquanto não houver instrumentação real das operações nativas. `GET /status` reúne estado do core/API, contagens, latência, memória, atividade, alertas, métricas do processo e `rust:{status,available,operations,last_error}`. O objeto `core` inclui `complete` e `stale_reason`; seu `status` é `ready` e `conclusions` contém a contagem somente quando o `ReasonerState` está completo para o store atual. Caso contrário, `core.status` é `incomplete` e `core.conclusions` é `null`. `available` só fica verdadeiro após verificação efetiva da biblioteca.

## Eventos

`POST /events` enfileira evento validado (`entity.add`, `fact.add` ou `fact.remove`) com source, payload opcionalmente provenance e `event_id` idempotente. `GET /events?event_type=&status=&after=&limit=` lê o log sequenciado com tentativa, estado e erro; ele é durável somente com persistência habilitada e fica em SQLite `:memory:` quando desabilitada. `POST /events/process` aceita `{limit?:number}`; quando `limit` é omitido ou `null`, usa `event_batch_size` da configuração. `POST /events/{event_id}/retry` reenfileira uma falha terminal.

O Event Engine é **at-least-once**, não exactly-once. A fila e o snapshot de conhecimento são transações distintas. Handlers são idempotentes por evento/proveniência; uma queda depois do efeito e antes do ack pode entregar novamente. Processar um evento que muda o store invalida o cache de consultas e produz notificações de conhecimento e de eventos.

## WebSocket

O endpoint `/ws` aceita somente uma sessão autorizada e um `Origin` exatamente presente na allowlist: `localhost`/`127.0.0.1` nas portas 3000/5173, mais `AETHER_ALLOWED_ORIGINS` e `--public-origin` configurados. Não há wildcard CORS nem Origin normalizado por remoção de caminho.

A primeira mensagem é um snapshot. Depois, o servidor publica apenas mensagens derivadas de estado real:

- `knowledge.changed`: mutação de entidade, fato/evidência, regra ou efeito aplicado por evento;
- `consistency.changed`: registro de uma revisão humana de conflito;
- `events.changed`: enqueue, processamento ou retry;
- `metrics`: amostra de métricas, inclusive em resposta ao texto `ping`;
- `snapshot`: estado inicial.

Mensagens diferentes de `ping` não executam operações; retornam erro. A conexão revalida a sessão após cada mensagem e em intervalos limitados, encerrando após logout ou expiração da sessão. A sessão Preview opaca não reconsulta o provedor; sua expiração é limitada pelo `exp` do JWT validado na emissão, mas revogação antecipada não pode ser detectada sem introspecção. O cliente deve refazer as leituras REST relevantes após uma notificação e limpar o socket ao desmontar a tela.

## Erros e limites de segurança

Erros usam `{detail:string|object}` e status 400, 401, 403, 404, 409, 422 ou 429 conforme a causa. Retirada de ID malformado retorna 422; fato/evidência inexistente retorna 404; leitor sem papel de operador ou mutação sem CSRF recebe 403. Resolução sem conflito contradito, com evidência insuficiente ou seleção fora do conjunto atual retorna erro de validação. Validação rejeita objetos compostos em campos escalares, números não finitos, payloads fora dos limites e regras malformadas. Login tem rate limit local. A API não oferece execução de código, expansão JSON recursiva ilimitada, leitura de arquivos, path remoto ou query arbitrária.

O estado é serializado por lock dentro do processo. Snapshot de conhecimento, regras, memória cold e fila de eventos têm persistências separadas. Reinício restaura fatos, regras, config e cold tier quando habilitados, mas sessões são apenas em memória e precisam ser refeitas.

## Testes

No checkout, com o extra API instalado:

```bash
python -m unittest discover -s tests -p 'test*.py' -v
python -m pytest -q
```

Os testes de API são `unittest`-compatíveis e também executam sob pytest. Os números efetivos da execução e as limitações observadas ficam em [API_CONTRACT_NOTES.md](API_CONTRACT_NOTES.md).
