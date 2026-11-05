# Capturas reais do AETHER Studio

As capturas abaixo vieram do Playwright/Chromium contra a aplicação React/Vite e a API FastAPI locais, com sessão operador temporária e store descartável. A primeira metade usa entidades/fatos/regras efetivamente criados pela UI durante o cenário E2E; o teste remove seu fato de suporte antes de encerrar. As demais páginas mostram o estado real retornado pelo mesmo runtime. Não são screenshots de mockup nem de dados de produção.

## Telas integradas

![Dashboard real do E2E; o estado incompleto após remoção de suporte é mostrado explicitamente](../screenshots/studio/dashboard.png)

![Knowledge Explorer com entidades e fato de fixture criados pela interface](../screenshots/studio/knowledge.png)

![Knowledge Graph com a relação efetiva retornada pela API](../screenshots/studio/graph.png)

![Reasoning Console com conclusão derivada pela regra criada no E2E](../screenshots/studio/reasoning.png)

![Proof Explorer com prova derivada, suporte explícito e link fact #id](../screenshots/studio/proofs.png)

## Operação e responsividade

| Página | Captura |
|---|---|
| Memory Center | [Abrir PNG](../screenshots/studio/memory.png) |
| Event Monitor | [Abrir PNG](../screenshots/studio/events.png) |
| Performance Monitor | [Abrir PNG](../screenshots/studio/performance.png) |
| Settings | [Abrir PNG](../screenshots/studio/settings.png) |
| Navegação móvel (390 px) | [Abrir PNG](../screenshots/studio/mobile-menu.png) |

O Dashboard captura a condição pós-remoção em que o motor declara que precisa recomputar provas alternativas: o indicador `incomplete` é intencional e demonstra que o Studio não mascara como pronta uma conclusão obsoleta. Os dados são descartáveis e o cenário não altera dados de usuário/produção.
