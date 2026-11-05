# Benchmarks e dados

Cada script histórico vive em `benchmarks/phaseN/`; comandos flat continuam disponíveis temporariamente como entrypoints de compatibilidade. Execute os comandos documentados no README, preferindo `python -m benchmarks.phaseN.module` e diretório `--out` novo. Benchmarks completos podem ser longos; valide primeiro com configuração mínima.

`datasets/manifests/phase5_datasets.json` é a única cópia versionada do manifesto. Os arquivos SNAP grandes não são incluídos; obtenha-os conforme suas condições de uso e confira SHA-256. Scripts descobrem o checkout e o manifesto por helper comum, não por cwd.

`results/phaseN/` contém evidências históricas e não deve ser sobrescrito. Métricas RSS são bytes/KiB com unidades explícitas; quando o sistema não fornece métrica confiável, valor é nulo. Diferencie resultados de pesquisa, smoke tests e CI.
