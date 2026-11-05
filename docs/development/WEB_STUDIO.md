# AETHER Studio

AETHER Studio opera o núcleo real por FastAPI. Nenhuma página injeta números de demonstração quando a API está desconectada. Estado vazio, erro HTTP e métrica indisponível são mostrados explicitamente. Dados de teste só entram quando você escolhe `--seed-fixture`; permanecem fatos reais do store, rotulados como fixture, e não se confundem com dados de produção.

## Inicialização local

Depois de instalar Python e Node, no checkout:

```bash
python -m pip install -e ".[api]"
pnpm --dir frontend install --frozen-lockfile
python scripts/run_studio.py
```

Abra `http://localhost:3000`. A API escuta `127.0.0.1:8000`; o Vite encaminha `/api` e `/ws`, por isso o cliente não embute um host privado. `--api-only` e `--frontend-only` permitem processos separados. `--api-port`, `--frontend-port` e `--data-dir` são opções do launcher; `--seed-fixture` carrega o fixture somente em store vazio. Ctrl+C encerra ambos os processos. Mantenha apenas um worker/processo de API por diretório de dados.

A autenticação é obrigatória. Instalação independente usa o modo token configurado no servidor; o token fica no arquivo privado indicado pela API ou em `AETHER_OPERATOR_TOKEN`, nunca no código frontend. O formulário troca o token por sessão HttpOnly e limpa o valor digitado. No ambiente gerenciado, o login é Manus OAuth; um usuário autenticado não se torna operador automaticamente. Configure `AETHER_OPERATOR_OPEN_IDS` no servidor para autorizar escrita; leitores continuam podendo inspecionar status, fatos, provas e métricas. A sessão mostra o ID autenticado para facilitar esse cadastro administrativo.

## Navegação

**Dashboard** mostra o estado do núcleo/API/Rust e medidas observadas de memória, consultas, eventos e latência. CPU indisponível não vira zero. Rust compilado/disponível não significa que cada consulta passou pelo código nativo.

**Knowledge Explorer** permite pesquisar entidades, filtrar fatos por predicado, ver propriedades/evidências e consultar histórico. Operadores podem criar/editar entidades e fatos e remover fatos. O tipo do objeto é escolhido separadamente: booleano, inteiro, float, texto e null continuam distintos no motor. Alterar a chave de um fato é uma substituição explícita, não edição silenciosa de uma evidência.

**Grafo** usa relações entre entidades fornecidas pela API. Controles permitem zoom, ajuste da vista, pan e arrasto; selecionar um nó mostra propriedades e fatos relacionados. Filtro de predicado e expansão de vizinhança não inventam relações faltantes. O indicador de truncamento é mantido quando o limite de nós/arestas é atingido.

**Reasoning Console** aceita padrões relacionais com variáveis prefixadas por `?`, por exemplo `(?x, sent_email_to, ?y)`. Selecione estratégia e execute. Metas abertas exigem um caminho capaz de enumerar bindings; backward/híbrido dirigidos a prova fechada podem rejeitar padrões abertos com erro útil. Resultado incompleto exibe o motivo e o próximo offset quando existe paginação. Um resultado sem solução e incompleto não prova que a relação é falsa. Regras podem ser registradas explicitamente; não há interpretação/execução arbitrária de Python.

**Proof Explorer** abre a explicação de uma conclusão e suas alternativas, com regra/revisão, profundidade, suportes e proveniência. As evidências explícitas originais continuam navegáveis. Remover um suporte elimina apenas provas dependentes: uma alternativa independente pode manter a conclusão.

**Memory Center** exibe tiers, orçamento, estatísticas, padrões, evicções, cold tier e recuperação do cache real. Seu orçamento mede payload residente, não todo o RSS do processo Python. Frequência é observação operacional, não aprendizado de uma verdade semântica.

**Event Monitor** mostra eventos duráveis, fila, tentativas e falhas; operadores podem enfileirar tipos validados, processar lotes e reenfileirar falhas permitidas. Notificações WebSocket avisam alterações e disparam leituras atualizadas. Status offline não muda a garantia at-least-once do log.

**Performance Monitor** permite consultar períodos de amostras reais de CPU/memória/consultas/eventos/latência e comparação de estratégias executadas. Um histórico recém-iniciado pode não ter amostras suficientes. Valores `null` permanecem indisponíveis; throughput derivado de janela não é benchmark de capacidade máxima.

**Settings** valida orçamento, limites de inferência, estratégia, planner de join, persistência, componentes e lote de eventos no backend. Configuração inválida é recusada; a interface não pode fornecer paths arbitrários ou segredos.

## Fluxo mínimo integrado

Crie três entidades, acrescente duas relações de uma cadeia e registre uma regra transitiva. Consulte a conclusão, abra suas provas e veja os dois fatos originais. Remova um fato de suporte, refaça a consulta e confira a atualização; abra o histórico para inspecionar as mutações. Para testar provas alternativas, acrescente outra cadeia independente antes de remover a primeira. Esses passos devem usar o mesmo store e a mesma API, não uma demonstração isolada.

## Testes e diagnóstico

```bash
python -m unittest discover -s tests -v
pnpm --dir frontend typecheck
pnpm --dir frontend test
pnpm --dir frontend build
```

OpenAPI fica em `/docs` na origem da API conforme sua política de autenticação. Erros de rede aparecem na interface; primeiro confira se API e Vite estão ativos no mesmo checkout e se a sessão tem papel autorizado. O README e o relatório de entrega mostram capturas reais e os sistemas realmente testados. Matriz CI configurada não equivale a execução aprovada em Windows/Linux.

As capturas reais produzidas pelo browser autenticado, inclusive grafo e prova com as próprias entidades/fatos do E2E e vista móvel, estão na [galeria do AETHER Studio](STUDIO_SCREENSHOTS.md). São arquivos do ambiente de teste descartável; o dashboard pós-remoção preserva honestamente o estado `incomplete` enquanto o núcleo precisa recompor provas alternativas.
