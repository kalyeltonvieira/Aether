# Notas do contrato da API

## Escopo desta entrega

A camada FastAPI em `src/aether/interfaces/api/` foi concluída sobre os componentes canônicos do núcleo. A implementação não duplica o motor de conhecimento no browser nem cria dados de demonstração por padrão. O contrato público detalhado está em [API.md](API.md); os requisitos de Studio que motivaram os endpoints estão em [STUDIO_CONTRACT.md](STUDIO_CONTRACT.md).

Pontos de segurança verificados:

- o import de `aether.interfaces.api.app` não cria `.aether-data`, SQLite ou uma segunda aplicação; a factory `create_app` deve ser usada por Uvicorn com `--factory`;
- Manus/Preview usa `webdev_app_session`; um JWT HS256 desconhecido nesse cookie só é aceito com `MANUS_JWT_SECRET`, `exp` vigente e `appId` exatamente correspondente ao projeto;
- a primeira requisição Preview pode trocar o JWT por uma sessão opaca no mesmo cookie e ainda recebe a resposta de sessão correta;
- Manus OAuth oficial usa `MANUS_OAUTH_PORTAL_URL/app-auth` e os métodos `ExchangeToken`/`GetUserInfo` em `MANUS_OAUTH_API_URL`; state base64 com redirect+nonce é de uso único e vinculado ao cookie; o callback emite sessão e redireciona ao `/` fixo;
- leitor autenticado permanece `reader` por padrão; operador exige allowlist de `openId` no servidor;
- token independente é explícito e usa `AETHER_OPERATOR_TOKEN` ou arquivo privado gerado `operator-token`; o token não é impresso nem retornado;
- modo token usa `aether_studio_session`, modo Manus usa `webdev_app_session`;
- mutações exigem papel operador e `X-CSRF-Token`; CORS e Origin de WebSocket são listas finitas;
- cookies HTTPS Preview configurados com `--public-origin https://...` usam `Secure; SameSite=None`; HTTP local usa `SameSite=Strict`;
- erros de validação são sanitizados antes de JSON para não vazar objetos `ValueError` não serializáveis;
- sockets revalidam a sessão após mensagens e em intervalos limitados, sem deixar um `recv` indefinido autorizar uma sessão revogada.

Pontos de consistência verificados:

- leituras de status, memória, config, métricas, store e regras usam o lock da instância;
- `fact.add`, `fact.remove`, entidades e regras passam pelos serviços do core real;
- o Event Engine processa a mesma instância de `KnowledgeReasoner`/`KnowledgeStore` usada pelas rotas REST;
- processamento de evento que altera o store limpa o cache de consulta e publica `events.changed` e `knowledge.changed`;
- snapshots, regras, config, memória cold e fila de eventos sobrevivem a reinício em seus mecanismos próprios;
- valores `bool`, `int`, `float`, `str` e `null` mantêm `object_type` e identidade tipada;
- soluções de query expõem `object_type`, e todos os nós da árvore de explicação expõem `key_type` para preservar links escalares recursivos;
- o planner padrão continua `input`; `default_strategy` aceita `forward`, `backward` ou `hybrid`, enquanto `adaptive` permanece somente opção explícita porque o custo de decisão medido não justifica promovê-lo;
- status Rust só informa disponibilidade depois de localizar/carregar a biblioteca real; `operations` e `rust_operations` ficam `null` até existir instrumentação nativa observada. A API não compila Rust nem inventa contadores;
- o grafo ordena arestas por `fact_id` e retorna `total`, `offset`, `limit` e `next_offset` para continuação estável, inclusive na expansão por `center`;
- omitir `limit` em `POST /events/process` usa o `event_batch_size` persistido, em vez de um default obrigatório no payload.

## Verificação executada

Ambiente dedicado da API (separado do ambiente de baseline). A suíte API foi executada diretamente com unittest e pytest; a suíte geral foi executada com os mesmos comandos após as alterações finais. Atualize os números abaixo somente após uma nova execução completa do checkout:

```bash
python -m unittest discover -s tests -p 'test*.py' -v
python -m pytest -q
```

A cobertura API inclui autenticação token, CSRF, expiração de sessão, CORS, rejeição de Origin, JWT Preview com projeto/expiração, allowlist de operador, leitor default, cookies HTTPS, CRUD/provas/cache, valores tipados e metadados recursivos de tipo, regras/configuração e fallback de estratégia, restart, paginação estável do grafo, lote de eventos configurável, status incompleto, fila de eventos, invalidação de cache e notificações WebSocket.

## Limitações honestas

1. O wire contract OAuth é exercitado com um provider HTTP simulado; ainda não houve conclusão do login/callback junto ao provedor Manus real no navegador nesta sessão. Isso requer uma sessão OAuth válida e confirmar a política de redirect pública do projeto.
2. Sessões são process-local e se perdem ao reiniciar. O diretório de dados não é um armazenamento de sessões compartilhado.
3. O Event Engine é at-least-once. Snapshot e ack não são uma transação distribuída; uma queda entre efeito e confirmação pode redeliver um evento. A fila mantém FIFO serializado, não paralelismo ilimitado.
4. O orçamento de `AdaptiveMemory` limita bytes de payload residentes, não o RSS total do processo. CPU e RSS podem ser `null`; throughput é uma derivação da janela observada, não um SLA.
5. Rust permanece opcional. Sem biblioteca compilada/carregável, o status é `unavailable` e `rust_enabled=true` é recusado. Nenhuma compilação ocorre implicitamente na inicialização da API.
6. A persistência é um snapshot verificável, não log transacional de cada operação. Conhecimento, regras, memória e eventos usam arquivos/bancos distintos.
7. Limites de payload, paginação, regras, profundidade, operações e conclusões são deliberadamente finitos. Uma resposta incompleta mantém `complete:false` e não significa que a relação foi refutada.
8. O `TestClient` da versão instalada pode emitir um aviso de compatibilidade Starlette/httpx; isso não altera os resultados HTTP/WebSocket observados.
