# AETHER — auditoria inicial da Phase 8

**Data:** 2026-11-05  
**Branch de trabalho:** `phase8`, criada a partir de `origin/main`  
**Commit-base auditado:** `a50b265d187041f0491fdfad2b7c92ddd691fefb`  
**Estado inicial do checkout novo:** limpo; nenhuma modificação existente foi descartada.

## 1. Integridade do Git e escopo protegido

A auditoria atualizou as referências remotas e confirmou:

| Referência | Hash observado no início |
|---|---|
| `main` | `a50b265d187041f0491fdfad2b7c92ddd691fefb` |
| `phase7` | `233d193e0dac0167566610d161a4ca424509619e` |
| `phase7new` | `cd14200a86e8aa7e19c2cdf3880d81cdeadbfe35` |
| `phase8` remota | inexistente |

O commit-base da `main` tem como pais `e5045119b2a702451eaf6cb6a3a7a0f998c1facc` e `19bece7d51c26caa1d6cbb2f0e3c6db62e5db7d8`; a `main` incorporou o PR #7 de correções anterior. O PR #7 aparece como merged. A fase 8 começou em checkout separado para preservar o clone/branch anterior; nenhum commit foi feito nas branches protegidas `main`, `phase7` ou `phase7new`.

## 2. Documentação histórica lida

Foram lidos integralmente o `README.md` e os relatórios disponíveis das Fases 2, 3, 4, 5, 6, 7 e 7new, além das auditorias das Fases 5, 6 e 7. Os relatórios preservam decisões e resultados anteriores; a Phase 8 não deve substituir nem reinterpretar as medições com cargas, hosts ou janelas diferentes.

Os próprios relatórios registram resultados adaptativos negativos em mais de uma fase, os limites de proveniência/semântica da projeção SNAP e a exigência de não descrever relações estruturais como compreensão de linguagem ou conhecimento aberto. Essas ressalvas permanecem válidas.

## 3. Testes-base locais

No checkout Linux x86_64, Python 3.12.3, com Rust 1.99.1 habilitado, a execução inicial de `python3 -m unittest discover -v` terminou com:

```text
Ran 127 tests
OK
```

Esse resultado é a linha de base local da Phase 8, antes das alterações desta fase; não valida por si só a matriz multiplataforma.

## 4. CI remota na base auditada

A execução de GitHub Actions para o commit `a50b265` (run [42073547517](https://github.com/kalyeltonvieira/Aether/actions/runs/42073547517)) terminou com sucesso nos seis jobs Linux/macOS (Python 3.10, 3.12 e 3.13) e falhou nos três jobs Windows. Os erros são de compatibilidade, não foram ignorados:

- `resource` não existe no Windows. A importação transitiva de `phase3_bench.py` causa falhas em testes do controlador e benchmarks Phase 5; a importação inicial de `aether_bench.py` também impede carregar `test_aether_native`.
- `test_hash_mismatch_is_rejected` mantém aberto um `NamedTemporaryFile` e passa seu caminho ao loader, que tenta reabrir o arquivo no Windows, causando `PermissionError`.

A CI-base executou 112 testes por job Windows e registrou cinco erros em cada ambiente Windows. O fluxo atual encontra leituras de `/proc/self/status`, `/proc/cpuinfo` e `/proc/meminfo`, e pressupostos `ru_maxrss` em scripts de benchmark; devem ser tratados sem reduzir as asserções funcionais.

## 5. Riscos de correção técnica a investigar

A leitura inicial do `KnowledgeStore` mostra que sua identidade de fato e índice por objeto usam igualdade/hash padrão de Python. Assim, `True`, `1` e `1.0` são equivalentes na chave atual; `0.0` e `-0.0` também colidem. O modelo atual aceita apenas escalares (`str`, `int`, `float`, `bool`, `None`), não tuplas nem estruturas compostas. A mudança deverá declarar a compatibilidade/migração de dados persistidos se alterar IDs ou deduplicação.

Os demais requisitos — provas alternativas, consultas abertas com bindings, versão do índice Rust, proveniência ampliada, estados de conhecimento, ciclo de vida de regras e validade do benchmark adaptativo — serão tratados por auditorias e testes específicos antes de selecionar correções.

## 6. Critérios de conduta

- Não alterar `main`, `phase7` ou `phase7new`; não fazer merge automático.
- Manter cada mudança na branch `phase8`, derivada do commit-base acima.
- Preservar relatórios, resultados e datasets anteriores; resultados novos ficam em `results/phase8/`.
- Registrar falhas e ambientes indisponíveis em vez de alegar validação inexistente.
- Priorizar equivalência semântica e correção antes de otimizações.
