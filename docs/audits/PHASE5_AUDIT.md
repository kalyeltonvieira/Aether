# AETHER — Auditoria inicial e plano da Fase 5

**Data:** 2026-11-05
**Branch:** `phase5`, criada a partir de `f7f5c95` (`main`)
**Estado inicial:** árvore de trabalho limpa; nenhum artefato histórico foi alterado.

## Estado auditado

O repositório contém dois commits publicados. O primeiro introduziu o protótipo, relatórios das Fases 2 e 3, testes e resultados iniciais. O segundo acrescentou o backend Rust FFI, o benchmark da Fase 4, seus relatórios, testes e resultados. A branch de trabalho preserva `main` como referência reversível.

A auditoria identificou 29 arquivos CSV e 29 arquivos JSON de resultados. Todos foram analisados pelo parser correspondente. Não foram encontrados erros de leitura, linhas CSV malformadas ou indicadores de acurácia falsa. Foram examinadas 2.741 células de acurácia nos CSVs. Os arquivos antigos, inclusive smoke tests e resultados exploratórios, são evidência histórica e não serão sobrescritos.

O ambiente disponível para esta execução é Linux `aarch64`, Python 3.12.3, 64 bits, seis CPUs lógicas, 7,8 GiB de memória reportada e aproximadamente 39 GiB livres no volume do projeto. Windows não está disponível. `rustc` e `cargo` também não estavam instalados no começo da auditoria. Portanto, nenhum resultado desta sessão pode declarar suporte Windows testado; os testes Linux/Rust precisam ser repetidos após disponibilizar o toolchain.

A suíte inicial `python3 -m unittest discover -v` concluiu com seis testes aprovados. A classe de testes Rust foi pulada pelo próprio teste, pois `rustc` não estava instalado. A aprovação inicial, portanto, cobre apenas os backends Python.

## O que está implementado

- `aether_bench.py` é um protótipo de fecho transitivo incremental por bitsets, comparado a BFS em workloads sintéticos de inserção. O objetivo é alcançar reutilização de relações de alcançabilidade; não é uma arquitetura de inteligência geral.
- `aether_engine.py` seleciona, antes da execução, entre busca por bitsets e fecho por linhas usando coeficientes empíricos fixos. As rotas são exatas para inserções, mas a política não aprende com a carga corrente e o código do motor não oferece remoções.
- `aether_dynamic.py` mantém grafos dirigidos por conjuntos Python ou `array('I')`, com inserções, remoções e DFS iterativa. Remoções permanecem corretas porque as consultas percorrem a adjacência atual, não um fecho que poderia ficar obsoleto.
- `phase2_bench.py`, `phase3_bench.py` e `phase4_bench.py` são programas experimentais de benchmark, não APIs de produção. Os relatórios documentam bem limitações de amostra, escopo do relógio, RSS e ausência de medição de energia.
- `rust_dfs_kernel.rs` é um microkernel CSR executável separado. Ele não é a biblioteca FFI dinâmica.
- `aether_native.rs` e `aether_native.py` implementam um grafo dinâmico Rust com `Vec<Vec<u32>>`, exposto via `ctypes`. A carga inicial é importada em lote, mas updates e consultas posteriores usam uma chamada ABI por operação.
- `phase4_bench.py` mede vários backends Python e Rust em processos isolados e valida alcançabilidade com um oráculo BFS independente.
- O backend Python CSR é imutável e existe apenas como comparador para workloads estáticos.

## O que é experimental, incompleto ou redundante

Os controladores da Fase 2, Fase 3 e a política de memória da Fase 4 são experimentais. Os relatórios existentes já registram perdas frente a estratégias fixas em vários cenários e não recomendam ativá-los como padrão. Eles devem permanecer comparadores, não ser promovidos por presunção.

O protótipo de fecho incremental tem semântica diferente do grafo dinâmico com remoções. O primeiro pode reutilizar relações de alcançabilidade sob inserções; o segundo recalcula cada consulta sobre as arestas atuais. Não são substitutos diretos nem devem ser misturados no mesmo benchmark sem declarar o custo de atualização e as operações suportadas.

Os caminhos Rust e Python dos benchmarks repetem implementações de travessia para instrumentar cenários distintos. O kernel CSR não é redundância comprovadamente removível: ele responde a uma pergunta isolada de layout e custo da travessia, mas não é consumido como componente pelo AETHER FFI. O trabalho de comparação histórica e os relatórios são dependências documentais; não serão removidos.

Não há persistência do estado, histórico temporal, cache de consultas, caminho mínimo, recuperação de caminho ou API de vizinhança como capacidades públicas do núcleo. O benchmark com datasets públicos ainda não existe.

## Riscos de correção e portabilidade

1. `aether_native.py` usa `.so` como nome padrão e chama `rustc` sem selecionar extensão ou alvo por sistema. Isso impede a experiência de carregamento/compilação pedida no Windows.
2. A biblioteca não expõe versão da ABI, largura de ponteiro ou informação de compilação. O wrapper não valida compatibilidade antes de usar os símbolos.
3. Funções `extern "C"` desreferenciam ponteiros e alocam vetores sem uma camada explícita de contenção de panic. Um ponteiro nulo é tratado em vários pontos, mas um endereço arbitrário inválido não pode ser validado com segurança por uma API C; esse limite precisa ser documentado.
4. `aether_graph_add_edges` valida cada par durante a mutação. Um ID inválido que apareça tarde pode retornar erro após arestas anteriores já terem sido inseridas. A operação não é transacional.
5. O wrapper permite `close()`, mas não bloqueia chamadas subsequentes com uma exceção Python clara. Não há contrato de concorrência para o mesmo handle; consultas alteram buffers internos.
6. Inserção, remoção e busca de duplicata em cada linha Rust são lineares no grau daquela linha. A representação é mutável, mas não é CSR.
7. Os benchmarks existentes importam `resource`, leem `/proc` e interpretam `ru_maxrss` com pressupostos Linux. Não são portáveis ao Windows sem adaptações específicas de medição.
8. `README.md` cita `rust_bfs_kernel.rs`, mas o arquivo presente é `rust_dfs_kernel.rs`; esse nome divergente precisa ser corrigido na documentação nova sem reescrever resultados antigos.
9. IDs são limitados a 32 bits na representação compacta. Não existe suporte documentado a concorrência nem a atualização temporal com remoção histórica.

## Gargalos observados e limites das evidências

Os relatórios das Fases 2–4 indicam que o fecho pode ser mais custoso em workloads de poucas consultas e muitas atualizações; o armazenamento compacto economiza memória sem assegurar menor latência; os controladores adaptativos avaliados não superam consistentemente a melhor estratégia fixa. A Fase 4 relatou benefícios end-to-end do Rust em grafos DAG sintéticos, mas cada consulta/update ainda cruza o FFI separadamente.

As cargas existentes são sintéticas. As medições antigas não serão tratadas como resultados com dados reais nem combinadas com novas medidas sem distinguir ambiente, versão, workload e relógio. O microbenchmark Rust/CSR da Fase 3 exclui construção, conversão, parsing e startup e permanece estritamente uma medida de kernel.

## Problema e solução propostos antes da mudança arquitetural

**Problema:** o wrapper da biblioteca nativa assume Linux, não negocia/valida ABI e atravessa a fronteira FFI uma vez por consulta ou atualização. A ausência de operações de lote impede medir se o custo de chamada é relevante sem confundi-lo com cópia do grafo. Ainda não existe avaliação em grafos públicos reais nem uma nova operação de grafo validada além de alcançabilidade.

**Solução proposta:** preservar os motores existentes e seus resultados; tornar o carregador dependente da plataforma, com verificação explícita de símbolos/ABI e erros acionáveis; introduzir interfaces Rust em lote para consultas, inserções e remoções usando buffers fornecidos pelo chamador, sem transferir novamente o grafo; proteger as rotinas de fronteira contra panic recuperável e validar ponteiros nulos, comprimentos, overflow e IDs antes da mutação; documentar que endereços de memória arbitrários não são verificáveis em C. Os métodos individuais permanecem como baseline. O buffer de resposta continuará pertencendo a Python e poderá ser reutilizado.

Para o dado e as novas operações, a mudança será incremental: registrar origem, formato, transformação, hash SHA-256 e limites de licença de cada dataset aprovado; priorizar datasets cujo tamanho caiba na memória disponível; comparar exatamente as mesmas consultas e eventos para backends compatíveis; e prototipar histórico temporal separadamente. Uma capacidade adicional será selecionada apenas após os testes mostrarem semântica exata e custo mensurável. Nenhuma política adaptativa se torna padrão sem vencer uma rota fixa em dados não usados na calibração.

## Critérios de mudança e reversão

A branch `phase5` é a cópia reversível do trabalho desta fase. Os resultados `results/phase2`, `results/phase3` e `results/phase4` e relatórios anteriores são imutáveis nesta execução. Cada mudança maior ficará em arquivo/API separado quando possível. Se a execução de Windows não estiver acessível, o relatório final declarará implementação preparada e teste não realizado, nunca “compatibilidade testada”. Se a máquina ou duração não comportar um dataset, ele será omitido com motivo, não substituído por resultado inventado.
