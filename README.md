
## Fase 7: conhecimento estruturado e raciocínio relacional

A Fase 7 adiciona uma camada experimental em `aether_knowledge.py`, `aether_inference.py`, `aether_consistency.py`, `aether_dependencies.py` e `aether_reasoner.py`. Ela representa entidades, fatos tipados, propriedades, proveniência, regras determinísticas, conclusões com dependências e invalidação localizada. A sessão marca adições como `stale` até recomputação e não declara incrementalidade completa quando provas alternativas podem existir.

Reproduza os testes e o benchmark controlado com:

```bash
python3 -m unittest discover -v
python3 phase7_bench.py --out results/phase7/knowledge_benchmark --seeds 30
```

O benchmark separa 15 seeds de calibração e 15 holdout em cada uma de duas famílias sintéticas. Os dados são fixtures de software, não treinamento e não conhecimento aberto. Resultados, procedência, CSV e gráfico ficam em `results/phase7/knowledge_benchmark/`; o escopo e os critérios ainda pendentes estão em [`PHASE7_REPORT.md`](PHASE7_REPORT.md).
