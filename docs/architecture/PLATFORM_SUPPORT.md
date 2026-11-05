# Suporte de plataforma — evidência e pendências

- Python puro: exige Python 3.10+; a execução local Linux antes da migração passou 127/127 testes em Python 3.12.3.
- CI base no SHA `a50b265d187041f0491fdfad2b7c92ddd691fefb`: Linux 3/3 e macOS 3/3 passaram; Windows 0/3 falhou por imports Unix-only e um temporário reaberto/removido enquanto ainda estava aberto.
- A integração `ctypes` seleciona `.dll`, `.so`, `.dylib` e valida SO/arquitetura/ABI antes de uso. Rust precisa ser compilado no host/target; binários não são compartilháveis entre sistemas.
- Linux ARM64 ainda não tem evidência de runner nesta configuração. Não declarado testado.
- O resultado da CI da branch de reorganização será atualizado no relatório final após execução real. Este documento não antecipa aprovação Windows ou Linux pós-migração.
