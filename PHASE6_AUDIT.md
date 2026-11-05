# AETHER — Auditoria inicial e plano técnico da Fase 6

**Data:** 2026-11-05  
**Branch de segurança:** `phase6`, criada a partir de `origin/phase5` no commit `f804026`  
**Estado antes da auditoria:** árvore limpa; `main`, `phase5` e resultados históricos preservados.

## 1. Estado do repositório

A Fase 5 está publicada e contém:

- ABI Rust v2 com `ctypes`, importação/mutação/consultas em lote e validação de ABI, plataforma e arquitetura;
- backends Python por conjuntos, adjacency compacta e CSR estático;
- cache LRU com invalidação global conservadora;
- histórico temporal por log compacto, com replay sem snapshots persistentes;
- componentes fracamente conectados por union-find, sempre recalculados do zero;
- benchmarks SNAP reais, sintéticos, temporais, NetworkX e gráficos já versionados;
- 47 testes automatizados e resultados históricos das Fases 1–5.

A árvore contém arquivos de build e caches locais ignorados pelo Git (`build/`, `__pycache__/`), além dos arquivos-fonte e resultados versionados. Nenhum resultado anterior será sobrescrito.

## 2. Auditoria das limitações relevantes

### Memória adaptativa

O cache existente memoriza apenas respostas exatas de alcançabilidade. Ele não distingue memória de curto prazo, memória persistente e memória fria, não registra frequência de acesso por região, não compacta entradas frias e não persiste resultados em armazenamento. Sua invalidação é global após qualquer mutação efetiva. Isso é reutilização de resultados, não aprendizado de padrões.

**Decisão:** introduzir uma camada separada, experimental e mensurável, com orçamento explícito, classes hot/warm/cold, deduplicação por chave de conteúdo, contadores de acesso e persistência opcional em arquivo local. O núcleo de grafo continuará correto mesmo quando a camada adaptativa for desativada ou perder entradas.

### Aprendizado incremental de padrões

A Fase 5 gera workloads determinísticos e mede cache, mas não mantém um modelo de sequências, regiões ou frequência que altere incrementalmente uma decisão. O controlador online anterior usa EMA de tempos de consulta, porém os relatórios mostram perda frente a estratégias fixas em vários cenários.

**Decisão:** implementar um detector incremental simples e auditável — contagem saturada de pares, regiões e transições de operações — e medir seu custo separado. O detector não será chamado de aprendizado geral e não será ativado como padrão sem vencer a melhor rota fixa em workloads não usados na calibração.

### Histórico e checkpoints

`TemporalEdgeHistory` mantém quatro arrays paralelos e reconstrói qualquer estado por replay completo. A Fase 5 encontrou aproximadamente 35,1 MB para log + estado atual contra 79,9 MB para cinco snapshots materializados, mas máximo observado de 8.042,5 ms para reconstrução histórica.

**Decisão:** adicionar checkpoints seletivos adaptativos. A política considerará eventos desde o último checkpoint, tempo de replay observado, custo de materialização e orçamento de memória. O benchmark comparará replay completo, snapshots periódicos, checkpoints adaptativos e compactação de eventos. A recuperação deverá ser conferida contra replay independente; a política não poderá ocultar o custo de manutenção.

### Componentes

`weak_component_labels()` usa union-find, mas percorre toda a adjacência e recalcula todos os rótulos em cada chamada. Inserções poderiam unir componentes incrementalmente; remoções podem dividir uma componente e exigem busca/recomputação localizada ou fallback seguro.

**Decisão:** implementar uma estrutura incremental experimental com união para inserções, detecção de aresta-ponte e recomputação somente da componente afetada quando uma remoção puder dividir o componente. Se a manutenção local não puder provar a correção, o algoritmo usará recomputação completa como fallback e registrará esse fato; não será declarado incremental além do que for medido.

### Controlador

A política por características e o controlador EMA existem, mas a Fase 5 e os relatórios anteriores mostram perdas frente a estratégias fixas. Não há validação rigorosa em workload não visto com custo de conversão e histerese integrados.

**Decisão:** criar um controlador de portfólio com exploração limitada, histórico por assinatura de workload, custo de decisão e histerese. A assinatura incluirá nós, arestas, densidade, razão update/query, lote, orçamento e backend disponível. A calibração será separada da avaliação holdout. O controlador só poderá ser recomendado como padrão se sua mediana end-to-end superar a melhor estratégia fixa no holdout; caso contrário, permanecerá opt-in.

### Concorrência

O wrapper Rust serializa chamadas no mesmo handle com `RLock`; a Fase 5 não mediu múltiplos handles concorrentes. O núcleo Rust reutiliza `marks` e `stack`, portanto compartilhar o mesmo objeto sem serialização seria inseguro.

**Decisão:** avaliar múltiplos handles independentes e consultas paralelas por partição de workload. Não haverá estado global compartilhado. O benchmark medirá throughput, latência por consulta, CPU, consistência e contenção; se a cópia/construção dos handles dominar, o relatório registrará resultado negativo.

### Portabilidade

O wrapper já seleciona `.so`, `.dll` e `.dylib`, mas a execução histórica foi Linux ARM64. Nesta sessão atual, `rustc` e `cargo` não estão no `PATH`; Windows 10/11 não está disponível.

**Decisão:** testar Linux/Rust somente após instalar um toolchain verificável. Windows será declarado como implementado/documentado, mas não validado, salvo execução real em Windows. Nenhum resultado será inventado ou transferido entre plataformas.

## 3. Plano de implementação em incrementos

1. **Fundação e contratos:** adicionar tipos de eventos, assinaturas de workload, métricas comuns, oráculos e testes de invariantes sem alterar APIs históricas.
2. **Memória adaptativa:** implementar hot/warm/cold, orçamento, deduplicação, persistência opcional e recuperação seletiva; comparar pelo menos três políticas.
3. **Padrões incrementais:** implementar contadores de frequência e transições, atualização O(1) por evento e integração somente como observador inicialmente.
4. **Checkpoints:** adicionar checkpoints periódicos, adaptativos e compactação de eventos; medir replay e manutenção no `sx-askubuntu` e fixtures com remoções.
5. **Componentes incrementais:** inserir união incremental e remoção com componente afetada/fallback completo; validar cada mutação contra BFS/rotulagem independente.
6. **Controlador holdout:** implementar histórico de desempenho, exploração limitada, histerese e fallback; calibrar em seeds distintas das usadas no holdout.
7. **Concorrência:** testar handles independentes, execução sequencial versus paralela e workloads equivalentes; não tornar paralelismo obrigatório.
8. **Rust e plataformas:** reinstalar/testar Rust no Linux disponível; compilar ABI em pelo menos Linux; documentar Windows como não validado se não houver máquina Windows.
9. **Benchmark e relatório:** executar sintéticos com 30 seeds, SNAP real quando os arquivos estiverem disponíveis, medir memória/CPU/latência/throughput e gerar CSV, JSON, gráficos e `PHASE6_REPORT.md`.

## 4. Critérios de aceitação

- Toda nova resposta estrutural coincide com um oráculo independente.
- A suíte anterior continua passando sem alterar seus resultados.
- Memória adaptativa respeita orçamento e não devolve resultados obsoletos após mutações.
- Checkpoints adaptativos recuperam estados exatamente e registram custo de manutenção.
- Componentes incrementais identificam corretamente fusões e divisões; fallback é visível nos resultados.
- O controlador publica custo de decisão, rota escolhida, taxa de exploração e comparação com melhor fixa. Não será padrão se perder no holdout.
- Concorrência usa handles isolados, não apresenta corrida observável e compara o custo total, não somente o kernel.
- Windows só aparece como validado se a bateria for executada em Windows 10/11.
- Nenhuma métrica de energia, FLOPs ou capacidade não medida será inventada.
- Resultados das Fases 1–5 permanecem byte a byte preservados.

## 5. Escopo que não será prometido

A Fase 6 não transformará o AETHER em chatbot, wrapper de LLM ou sistema de inteligência geral. Também não prometerá aprendizado semântico, conhecimento aberto, generalização para tarefas não estruturais ou eficiência universal. O foco é memória operacional, padrões de acesso, estado temporal, componentes e seleção mensurável de estratégias sobre relações estruturadas.

## 6. Riscos e fallback

O maior risco técnico é a manutenção correta de componentes após remoções: quando não houver prova local suficiente, a estrutura deve recomputar a componente ou o grafo inteiro. O segundo risco é o controlador pagar mais pela exploração do que economiza. O terceiro é a ausência do toolchain Rust/Windows no ambiente atual. Em todos os três casos, a saída aceitável é um fallback correto e um resultado negativo documentado, não uma alegação de suporte ou ganho.

Este documento é o marco da auditoria. Implementações da Fase 6 devem ser feitas em commits posteriores, com testes e benchmarks separados dos resultados históricos.
