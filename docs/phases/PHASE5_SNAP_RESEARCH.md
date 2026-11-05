# Fontes e seleção dos datasets SNAP — Fase 5

## Condições de uso e método de seleção

As fichas oficiais dos datasets e a página de licença do SNAP foram verificadas antes de qualquer download. A página `License` publica BSD para o software/biblioteca SNAP; ela não declara essa licença para os arquivos de dados. As páginas oficiais consultadas tampouco apresentam termos ou licença específicos para os sete datasets abaixo. Portanto, o status dos dados fica registrado como **licença/termos específicos não localizados**. Isso não equivale a domínio público, permissão de redistribuição ou licença BSD. Os arquivos baixados para os ensaios serão usados localmente; os binários dos datasets não serão incluídos no repositório. [8] [9]

A seleção principal será `email-Eu-core` para pequeno, `wiki-Vote` para médio, `soc-Epinions1` para médio/grande e `web-Google` para grande. `sx-askubuntu` será usado separadamente para o protótipo temporal, pois sua página documenta eventos `SRC DST UNIXTS`. Esse conjunto cobre de 1.005 até 875.713 nós e inclui uma fonte com timestamps explícitos. O perfil do ambiente observado foi de 13 GiB de memória disponível, 6 CPUs e 38 GiB livres em disco. `web-Stanford` fica como alternativa intermediária. `roadNet-CA` fica fora da execução principal: contém quase 2 milhões de nós não dirigidos, cuja representação no AETHER exigiria registrar a transformação simétrica e duplicaria aproximadamente o número de arcos. A matriz completa de múltiplos métodos, sementes e repetições sobre os conjuntos selecionados já limita o tempo de CPU e a memória do baseline Python. [1] [2]

Os arquivos listados como TXT/GZIP serão preservados sem alteração. Para os quatro datasets dirigidos estáticos, as arestas permanecem dirigidas e não são espelhadas. Para `sx-askubuntu`, cada linha temporal será mantida como evento, incluindo interações repetidas; a relação atual será uma aresta dirigida única após sua primeira inserção. A contagem de eventos e a contagem de relações estáticas serão registradas separadamente. A estrutura de linhas de arquivos estáticos que não é especificada pelas páginas será descrita somente após a inspeção do arquivo baixado.

## Datasets selecionados

**`email-Eu-core` — pequeno, estático e dirigido.** O SNAP publica 1.005 nós e 25.571 arestas. A semântica é que existe uma aresta dirigida `u → v` quando `u` enviou ao menos um e-mail para `v`. A página publica `email-Eu-core.txt.gz`, mas não documenta o esquema completo das linhas do arquivo. Timestamps não foram publicados para a versão estática; `email-Eu-core-temporal` é uma variante distinta e não será usada para substituir sua contagem original. [2] [1]

**`wiki-Vote` — médio, estático e dirigido.** O índice oficial publica 7.115 nós e 103.689 arestas. A descrição narrativa da página menciona 103.663 votos; a fonte não explica a diferença de 26, então os dois números não serão reconciliados por suposição. Um arco `i → j` representa um voto do usuário `i` em `j`. A extração usa o histórico da Wikipedia até janeiro de 2008, mas timestamps por aresta não foram confirmados; este dataset será tratado como grafo estático. [3] [1]

**`soc-Epinions1` — médio/grande, estático e dirigido.** O SNAP publica 75.879 nós e 508.837 arestas para a rede de confiança do Epinions. Essa contagem é da rede dirigida original. Algumas estatísticas publicadas pelo SNAP usam convenções não dirigidas para métricas, mas isso não constitui uma transformação do arquivo nem altera a contagem original de arestas usada aqui. A página lista `soc-Epinions1.txt.gz` e não documenta timestamps por relação. [4] [1]

**`web-Google` — grande, estático e dirigido.** O SNAP publica 875.713 nós e 5.105.039 arestas de hyperlinks dirigidos. A página lista `web-Google.txt.gz`; a data de liberação indicada para o conjunto não será interpretada como timestamp individual por aresta. Este dataset oferece a maior escala da seleção principal. [5] [1]

**`sx-askubuntu` — temporal, dirigido e baseado em eventos.** A página publica 159.316 nós, 964.437 eventos temporais, 596.933 arestas no grafo estático e janela de 2.613 dias. Cada linha `SRC DST UNIXTS` registra uma interação dirigida — resposta ou comentário — e o timestamp é Unix em segundos. As contagens de eventos e de relações agregadas são diferentes e serão reportadas separadamente. A fonte não documenta remoções de relações; o protótipo aceitará eventos `remove` para testes, mas nenhuma remoção será inventada para o log SNAP. [6] [7]

## Alternativas pesquisadas, não incluídas na execução principal

**`web-Stanford`.** A página publica 281.903 nós e 2.312.497 arestas dirigidas e lista `web-Stanford.txt.gz`. É um grafo estático; a coleta em 2002 não confirma timestamps por aresta. Foi omitido por ser uma escala intermediária entre `soc-Epinions1` e `web-Google`, sem ampliar tanto a cobertura quanto o custo de execução da matriz completa. [10] [1]

**`roadNet-CA`.** O SNAP publica 1.965.206 nós e 2.766.607 arestas não dirigidas. Se fosse incluído, cada ligação rodoviária seria transformada em dois arcos dirigidos; essa transformação precisaria ser explicitada e a contagem resultante seria distinta da contagem original. A escala por nó, a semântica de rede rodoviária e a conversão exigiriam uma avaliação própria. Nenhum arquivo será baixado para este ensaio. [11] [1]

## Hashes e formato efetivamente inspecionado

O manifesto `phase5_datasets.json` registra URL, tamanho e SHA-256 do `.txt.gz` original, antes da extração. As contagens observadas, autoarestas, duplicatas e transformações ficam registradas nos resultados. Nenhum arquivo foi reescrito para forçar uma coincidência com o índice SNAP; as verificações observadas estão abaixo.

## Inspeção dos arquivos baixados

`gzip -t` passou nos cinco arquivos. Nos quatro conjuntos estáticos selecionados, o número de arestas dirigidas únicas após leitura coincide com a estatística SNAP: 25.571 em `email-Eu-core`, 103.689 em `wiki-Vote`, 508.837 em `soc-Epinions1` e 5.105.039 em `web-Google`. Não foram removidos registros de aresta duplicados nesses arquivos. `email-Eu-core` contém 642 autoarestas, que foram preservadas; os outros três arquivos não continham autoarestas. Esses valores foram comparados às páginas oficiais de cada dataset. [2] [3] [4] [5]

`sx-askubuntu` contém 964.437 eventos, 596.933 relações dirigidas únicas e 367.504 eventos repetidos sobre uma relação já registrada. Os 159.316 IDs aparecem no arquivo, mas foram relabelados para um intervalo denso interno porque alguns IDs originais excedem o intervalo `0..n-1`. O arquivo não está ordenado cronologicamente; o protótipo ordenou eventos por timestamp e preservou a ordem original da linha nos empates. A janela medida é de 2.613,82 dias; a página publica 2.613 dias, valor arredondado. As contagens conferem com a fonte SNAP. [6] [7]

A página `wiki-Vote` mostra o rótulo `Wiki-Vote.txt.gz`, mas o href oficial utilizável é minúsculo no primeiro caractere: `https://snap.stanford.edu/data/wiki-Vote.txt.gz`. O servidor retorna 200 para o href e 404 para o caminho com `Wiki-Vote.txt.gz`; o manifesto conserva o href real, sem espelho ou alteração dos dados. [3]

## Referência externa para alcançabilidade

O comparador opcional usa `networkx.DiGraph` e `networkx.has_path(G, source, target)`, cuja documentação define o retorno como `True` quando há um caminho de `source` a `target`. O harness mede essa implementação Python separadamente e exige os mesmos hashes de consultas e updates do benchmark AETHER. [12]

## Referências

[1]: https://snap.stanford.edu/data/index.html "Stanford Large Network Dataset Collection"
[2]: https://snap.stanford.edu/data/email-Eu-core.html "SNAP email-Eu-core network"
[3]: https://snap.stanford.edu/data/wiki-Vote.html "SNAP Wikipedia vote network"
[4]: https://snap.stanford.edu/data/soc-Epinions1.html "SNAP Epinions social network"
[5]: https://snap.stanford.edu/data/web-Google.html "SNAP Google web graph"
[6]: https://snap.stanford.edu/data/sx-askubuntu.html "SNAP temporal Ask Ubuntu network"
[7]: https://snap.stanford.edu/temporal-motifs/data.html "SNAP temporal motif datasets"
[8]: https://snap.stanford.edu/snap/license.html "SNAP software license"
[9]: https://snap.stanford.edu/about.html "SNAP About"
[10]: https://snap.stanford.edu/data/web-Stanford.html "SNAP Stanford web graph"
[11]: https://snap.stanford.edu/data/roadNet-CA.html "SNAP California road network"
[12]: https://networkx.org/documentation/stable/reference/algorithms/generated/networkx.algorithms.shortest_paths.generic.has_path.html "NetworkX has_path API"
