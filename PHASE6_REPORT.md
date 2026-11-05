# AETHER — Fase 6: validação quantitativa final

**Branch:** `phase6`
**Commit de implementação anterior à validação:** `a7d5e4f`
**Toolchain validado:** `rustc 1.99.1`
**Data da validação:** 2026-11-05

## 1. Conclusão executiva

A Fase 6 está **parcialmente aprovada**: os seis subsistemas estão implementados, testados e exatos nos oráculos usados, mas não existe uma estratégia adaptativa universalmente superior. A implementação incremental de componentes apresenta o ganho quantitativo mais forte. O controlador, os checkpoints e a execução concorrente devem permanecer experimentais/opt-in porque perderam para alternativas fixas no custo total medido.

A validação final usou cinco arquivos SNAP locais (`email-eu-core`, `wiki-vote`, `soc-epinions1`, `web-google` e `sx-askubuntu`), 30 seeds holdout (`100..129`) não usadas na calibração do controlador (`0..9`) e prefixos determinísticos de até 900 relações por arquivo, com remapeamento denso documentado. Os arquivos originais não foram alterados.

Foram produzidas 13.200 linhas CSV: 450 de memória, 450 de checkpoints, 12.000 de componentes, 150 de controlador e 150 de concorrência. Todos os resultados de correção medidos no holdout foram exatos: estruturas temporais 100%, componentes 100% e consultas concorrentes 100%.

## 2. Integridade e testes

A branch `phase6` preservou os seis commits anteriores; `main` e `phase5` não foram alteradas. A suíte completa foi executada com Rust habilitado:

```text
Ran 73 tests in 5.230s
OK
```

O resultado inclui ABI/FFI nativa Rust, testes de buffers, concorrência pelo wrapper, memória adaptativa, checkpoints, componentes incrementais, controlador e consultas isoladas. Não houve teste Rust pulado nesta execução final. O toolchain verificável foi `rustc 1.99.1`.

Os resultados históricos das Fases 1–5 permanecem preservados: os arquivos de fase anteriores não foram editados; a comparação Git contra a base `origin/phase5` contém somente os novos artefatos da Fase 6 e o harness de validação.

## 3. Procedência SNAP

Os cinco arquivos disponíveis tiveram SHA-256 coincidente com o manifesto:

| Dataset | Estado do hash | Observação |
|---|---|---|
| `email-eu-core` | coincidente | arquivo oficial local |
| `wiki-vote` | coincidente | arquivo oficial local |
| `soc-epinions1` | coincidente | arquivo oficial local |
| `web-google` | coincidente | arquivo oficial local |
| `sx-askubuntu` | coincidente | arquivo temporal oficial local |

`web-Stanford` e `roadNet-CA` não estavam disponíveis localmente e não foram baixados nem substituídos. O manifesto continua distinguindo a licença BSD do software SNAP de eventuais termos específicos dos datasets; não foi inferida licença para os arquivos de dados.

A validação usou prefixos determinísticos dos arquivos locais para manter a matriz segura em memória. Cada prefixo preservou sua procedência, hash do arquivo original, tamanho, contagem amostrada e transformação em [`provenance.json`](results/phase6/final_holdout_v3/provenance.json). Seeds do mesmo dataset não são tratados como datasets independentes.

## 4. Memória adaptativa e padrões

Foram comparadas três políticas com a mesma carga, orçamento de 2 KiB, payloads de 256 bytes e 180 operações por execução:

| Política | Mediana do tempo total | Mediana de evacuações | Mediana de escritas cold |
|---|---:|---:|---:|
| `unbounded_lru` | **1,991 ms** | 170,5 | 0 |
| `bounded_lru` | 9,629 ms | 170,5 | 170,5 |
| `frequency_aware` | 9,540 ms | 170,5 | 170,5 |

A pressão de memória foi intencionalmente ajustada depois de uma primeira execução diagnóstica com 24 KiB, na qual nenhuma política evacuou entradas. Essa primeira execução (`final_holdout_v2`) foi preservada como evidência metodológica, mas não é usada como resultado final.

A conclusão é negativa para superioridade adaptativa: `unbounded_lru` foi aproximadamente 4,8 vezes mais rápido nesta carga porque não persistiu entradas; `frequency_aware` foi apenas 0,9% mais rápido que `bounded_lru`, com a mesma quantidade mediana de evacuações e persistências. Portanto, a política de frequência não demonstrou benefício suficiente para pagar sua manutenção. O detector incremental de padrões foi validado por testes, mas não deve ser chamado de aprendizado semântico: ele aprende apenas frequências e transições operacionais.

## 5. Checkpoints temporais

Foram comparados replay completo, checkpoints periódicos e checkpoints adaptativos em 500 eventos e 13 pontos de recuperação por execução:

| Estratégia | Mediana construção + recuperação | Mediana de eventos reproduzidos | Exatidão estrutural |
|---|---:|---:|---:|
| `replay` | **4,064 ms** | 4.493 no agregado da distribuição | 100% |
| `periodic` | 5,564 ms | 229 no agregado da distribuição | 100% |
| `adaptive` | 5,592 ms | 229 no agregado da distribuição | 100% |

A leitura principal é o trade-off: checkpoints reduziram o replay observado e mantiveram exatidão, mas construção e materialização ainda fizeram o custo total mediano ficar acima do replay puro nesta carga curta. A continuação da Fase 6 substituiu a restauração por inserções individuais pela cópia direta de linhas compactas: contra a medição anterior, `periodic` caiu 18,0% e `adaptive` caiu 16,3%. `adaptive` ficou praticamente empatado com `periodic`, mas ambos ainda perderam para `replay` no holdout curto. Em um ensaio diagnóstico com 200 recuperações, porém, `adaptive` venceu replay em cinco datasets prefixados; o benefício depende da quantidade de recuperações históricas. A política adaptativa não deve ser padrão sem workloads temporais mais longos ou consultas históricas mais frequentes.

Os testes focados da otimização passaram (15/15) e a suíte completa permaneceu em 73/73. O snapshot continua armazenando linhas imutáveis e a restauração mantém a mesma semântica para inserções, remoções, empates de timestamp e replay independente.

## 6. Componentes fracos incrementais

Foram executadas 12.000 operações de inserção/remoção, comparando atualização incremental com recomputação completa da partição. Todas as 12.000 respostas coincidiram com a rotulagem independente por union-find/BFS.

| Medida | Incremental | Recomputação completa |
|---|---:|---:|
| Mediana por atualização + verificação | **0,008057 ms** | 0,494116 ms |
| Razão mediana full/incremental | \\multicolumn{2}{c}{**61,3x**} |
| Taxa de exatidão | 100% | 100% |

A implementação faz união em inserções e busca somente a componente afetada em remoções. Arcos reversos foram testados explicitamente. O número de nós escaneados e os casos de divisão ficam registrados no CSV; a comparação inclui a verificação completa independente, portanto não deve ser interpretada como uma aceleração universal de todo o pipeline de validação.

## 7. Controlador adaptativo

O controlador foi calibrado nos seeds `0..9` e avaliado nos seeds `100..129`. O custo de decisão foi incluído na comparação:

- mediana controlador + decisão: **0,412034 ms**;
- mediana da melhor estratégia fixa observada: **0,407275 ms**;
- custo mediano da decisão: **0,009231 ms**;
- estratégia escolhida coincidiu com a melhor fixa em **92,67%** das linhas.

Apesar da alta taxa de escolha correta, o controlador perdeu aproximadamente 1,17% para a melhor fixa no custo mediano end-to-end. Isso atende ao requisito de medição e não ao requisito de superioridade. O controlador permanece experimental, com fallback seguro e desativado como padrão.

## 8. Consultas sequenciais e concorrentes

Foram comparadas consultas sequenciais e quatro handles isolados em paralelo, incluindo a construção dos handles:

- sequencial mediano, construção + consultas: **2,129 ms**;
- paralelo mediano, construção + consultas: **4,214 ms**;
- speedup end-to-end mediano: **0,296x**;
- exatidão: **100%**.

Nesta carga, o paralelismo perdeu porque a construção de quatro cópias e a coordenação superaram o ganho das consultas. Não há evidência para ativar concorrência automaticamente. O estado não é compartilhado entre handles; a execução nativa Rust continua protegida pela serialização por handle existente.

## 9. Comparação com a Fase 5

A Fase 5 terminou com 47 testes e 240 benchmarks reais, validando ABI v2, FFI em lote, cache, replay temporal e componentes recomputados. A Fase 6 elevou a suíte para 73 testes e acrescentou 13.200 linhas de medição holdout, mas seus ganhos não são uniformes:

- Fase 5 mostrou que FFI Rust em lote foi forte em `web-Google` e em vários grupos SNAP.
- Fase 6 mostrou ganho incremental claro em componentes fracos sob mutações, com 61,3x de diferença mediana contra recomputação no protocolo usado.
- Fase 6 não mostrou que checkpoints adaptativos vencem replay curto; o custo de manutenção dominou.
- Fase 6 não mostrou que o controlador vence a melhor rota fixa; ficou 1,17% pior na mediana incluindo decisão.
- Fase 6 não mostrou vantagem de concorrência com construção de handles; ficou 1,98x mais lenta que a execução sequencial mediana.
- A memória adaptativa demonstrou orçamento e persistência, mas a política mais simples foi a mais rápida na carga sob pressão; frequência não foi universalmente benéfica.

As latências não devem ser comparadas diretamente como se fossem o mesmo workload: a Fase 5 usou sua matriz real completa, enquanto esta validação usa prefixos SNAP densamente remapeados e métricas específicas de cada subsistema.

## 10. Critérios de aceitação

| Critério | Resultado |
|---|---|
| Respostas novas coincidem com oráculos independentes | **Atendido** — 100% nos campos de exatidão medidos |
| Suíte anterior continua passando | **Atendido** — 73 testes OK com Rust |
| Memória respeita orçamento e evita respostas obsoletas | **Atendido no escopo testado** — orçamento de 2 KiB e persistência verificados |
| Checkpoints recuperam estados exatamente | **Atendido** — 100% estrutural |
| Componentes lidam com fusões/divisões corretamente | **Atendido** — 100% em 12.000 operações |
| Controlador publica custo e comparação holdout | **Atendido** |
| Controlador supera melhor fixa no holdout | **Não atendido** — 0,412034 ms contra 0,407275 ms |
| Concorrência é correta e compara custo total | **Atendido quanto à correção; não quanto ao ganho** |
| Concorrência supera sequencial | **Não atendido** — speedup mediano 0,296x |
| Checkpoints adaptativos superam replay no end-to-end | **Não atendido nesta carga** |
| Windows 10/11 validado | **Não atendido** — não há máquina Windows disponível |
| Resultados Fases 1–5 preservados | **Atendido** |
| Resultados SNAP têm procedência e hashes | **Atendido para os cinco arquivos disponíveis** |

**Veredito:** a Fase 6 atende aos critérios de correção, reprodutibilidade, orçamento, procedência e transparência. A otimização da restauração melhorou substancialmente os checkpoints, mas ela **ainda não atende** aos critérios de demonstrar superioridade adaptativa universal, ganho concorrente ou compatibilidade Windows validada. Portanto, a Fase 6 deve ser considerada **validada experimentalmente, mas não pronta para declarar uma política adaptativa padrão**.

## 11. Limitações e falhas encontradas

1. `web-Stanford` e `roadNet-CA` não estão disponíveis localmente; não foram inventados dados nem feitos downloads adicionais.
2. Os benchmarks SNAP usam prefixos limitados e remapeamento denso; não substituem a matriz completa da Fase 5.
3. A política de memória armazena bytes opacos e mede acesso operacional, não relevância semântica.
4. A persistência cold foi medida por JSONL local, não por um sistema de armazenamento distribuído.
5. Checkpoints duplicam snapshots de arestas; a política adaptativa não compensou essa manutenção na carga curta.
6. A comparação de componentes mede o custo da mutação incremental contra mutação mais recomputação; o oráculo completo é deliberadamente independente.
7. O controlador pode escolher a melhor rota em muitos casos e ainda perder por custo de decisão e ruído.
8. Concorrência com handles independentes foi correta, mas mais lenta; não deve ser ativada sem uma carga maior que amortize construção.
9. Windows, energia, FLOPs e hardware heterogêneo permanecem não validados.

## 12. Artefatos

- Harness: [`phase6_validation.py`](phase6_validation.py)
- Resultado final: [`summary.json`](results/phase6/final_holdout_v4/summary.json)
- Procedência: [`provenance.json`](results/phase6/final_holdout_v4/provenance.json)
- Memória: [`memory_policies.csv`](results/phase6/final_holdout_v4/memory_policies.csv)
- Checkpoints: [`checkpoint_policies.csv`](results/phase6/final_holdout_v4/checkpoint_policies.csv)
- Componentes: [`components_incremental.csv`](results/phase6/final_holdout_v4/components_incremental.csv)
- Controlador: [`controller_holdout.csv`](results/phase6/final_holdout_v4/controller_holdout.csv)
- Concorrência: [`parallel_sequential.csv`](results/phase6/final_holdout_v4/parallel_sequential.csv)
- Gráficos: [`memory_policies.png`](results/phase6/final_holdout_v4/memory_policies.png), [`checkpoint_policies.png`](results/phase6/final_holdout_v4/checkpoint_policies.png), [`components_incremental.png`](results/phase6/final_holdout_v4/components_incremental.png), [`controller_holdout.png`](results/phase6/final_holdout_v4/controller_holdout.png), [`parallel_sequential.png`](results/phase6/final_holdout_v4/parallel_sequential.png)

O diretório `results/phase6/final_holdout_v2` contém a primeira execução diagnóstica preservada; ela revelou pressão de memória insuficiente e não é usada nas conclusões finais. A versão v3 é a medição anterior à otimização de checkpoints; a versão v4 é a medição definitiva após a correção do protocolo e da restauração.
