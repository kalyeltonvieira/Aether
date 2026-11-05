# Testes

```bash
python -m unittest discover -s tests -v
python -m unittest discover -s tests/portability -v
python -m unittest discover -s tests/concurrency -v
```

Os testes históricos foram preservados em `tests/unit`, `tests/integration`, `tests/regression` e `tests/concurrency`. `tests/portability` exercita imports canônicos/compatibilidade, métricas disponíveis/ausentes, paths com espaço e Unicode, temporários, recursos empacotados e import fora do checkout. Testes FFI requerem Rust e compilação para a máquina corrente.

A suíte não deve ignorar testes semânticos devido a indisponibilidade de métricas; valor indisponível é `None`. Windows precisa ser executado em CI de verdade para validar os contratos de temporários e DLL. ARM64 não deve ser declarado sem runner apropriado.
