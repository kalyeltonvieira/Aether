# Testes

```bash
python -m unittest discover -s tests -v
python -m unittest discover -s tests/portability -v
python -m unittest discover -s tests/concurrency -v
```

Os testes históricos foram preservados em `tests/unit`, `tests/integration`, `tests/regression` e `tests/concurrency`. `tests/portability` exercita imports canônicos/compatibilidade, métricas disponíveis/ausentes, paths com espaço e Unicode, temporários, recursos empacotados e import fora do checkout. Testes FFI requerem Rust e compilação para a máquina corrente.

A suíte não deve ignorar testes semânticos devido a indisponibilidade de métricas; valor indisponível é `None`. Windows precisa ser executado em CI de verdade para validar os contratos de temporários e DLL. ARM64 não deve ser declarado sem runner apropriado.

## API e Studio

Instale `python -m pip install -e ".[api]"` para não ignorar os testes opcionais de API. A suíte usa diretórios temporários, autenticação explícita de teste e o núcleo real; testa status/endpoints, validação, CSRF, papéis, sessão, WebSocket, persistência e o fluxo de fatos→regra→consulta→prova→remoção→histórico. Sem os extras, testes de API podem ser ignorados de maneira explícita; isso não representa aprovação da API.

```bash
pnpm --dir frontend install --frozen-lockfile
pnpm --dir frontend typecheck
pnpm --dir frontend test
pnpm --dir frontend build
```

Os testes unitários frontend usam fixtures de contrato somente dentro de testes, não como fallback da aplicação. Carregamento, erro, vazio, formulários, navegação e serviços de HTTP devem refletir os dados observados. O fluxo integrado usa API real e browser, com dados de teste explicitamente identificados. Capturas mostram a UI executada, não uma imagem gerada ou mockup.

CI mantém a matriz Python/Rust de Linux/macOS/Windows e acrescenta instalação/testes/build frontend em Linux/Windows. Registre a URL/run/commit e resultados efetivos: configurar uma matriz não comprova que a execução ocorreu. `windows-latest` é runner Windows, não substitui testes de GUI em Windows 10/11. Nenhum histórico de benchmark é regenerado na CI.
