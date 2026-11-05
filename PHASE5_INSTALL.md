# Instalação e execução — AETHER Fase 5

## Requisitos

O núcleo Python requer Python 3.10 ou posterior. A integração nativa requer Rust stable (`rustc`) com edição 2021 e um linker/runtime C apropriado ao sistema operacional. O núcleo não requer dependências Python externas. `matplotlib` e `numpy` são necessários somente para os gráficos. NetworkX é opcional e usado apenas no comparador externo; ele não é dependência de execução do AETHER.

A biblioteca é compilada automaticamente por `compile_native()` quando não há arquivo nativo no caminho esperado. O nome e a extensão dependem da plataforma atual: `build/libaether_native.so` no Linux, `build/aether_native.dll` no Windows e `build/libaether_native.dylib` no macOS. `AETHER_NATIVE_LIB` pode apontar para uma biblioteca já compilada; o wrapper só a aceita quando ABI, largura de ponteiro, plataforma e arquitetura forem compatíveis.

## Linux

Em uma distribuição Ubuntu/Debian, instale Python e ferramentas básicas com o gerenciador do sistema. Instale Rust stable pelo canal oficial do rustup e carregue o ambiente Rust no shell:

```bash
sudo apt-get update
sudo apt-get install -y python3 python3-venv build-essential curl
curl --proto '=https' --tlsv1.2 -sSf https://sh.rustup.rs | sh -s -- -y --profile minimal --default-toolchain stable
source "$HOME/.cargo/env"
```

Na raiz do repositório, compile e execute a suíte:

```bash
python3 -c 'from aether_native import compile_native; print(compile_native())'
python3 -m unittest discover -v
```

A primeira chamada grava a biblioteca em `build/`; esse diretório é ignorado pelo Git. O wrapper também pode compilá-la automaticamente ao criar `RustDynamicGraph`.

## Windows 10/11 — procedimento previsto, ainda não verificado nesta tarefa

Este caminho descreve como executar o mesmo código sem editar arquivos-fonte. Ele **não é uma declaração de suporte testado**: a execução da Fase 5 ocorreu em Linux ARM64. Não havia um computador Windows disponível para compilar a DLL e executar os testes nesta tarefa.

Instale Python 3.10+ e Rust stable para Windows a partir dos distribuidores oficiais. Para o alvo Rust MSVC padrão, instale também o Visual Studio Build Tools com a carga “Desktop development with C++”, que fornece linker e runtime. Abra um novo PowerShell e confirme `py --version` e `rustc --version`. Na raiz do repositório:

```powershell
py -3.12 -m venv .venv
.\.venv\Scripts\Activate.ps1
py -c "from aether_native import compile_native; print(compile_native())"
py -m unittest discover -v
```

`compile_native()` chama `rustc` para criar `build\aether_native.dll`. O wrapper usa `ctypes.CDLL`, verifica ABI v2 e recusa carregar uma biblioteca construída para Linux, outra arquitetura ou outra versão da ABI. A validação efetiva em Windows 10 e Windows 11 permanece pendente; execute os mesmos comandos nessas versões antes de declarar compatibilidade.

## Dados SNAP e benchmarks

As origens, URLs e condições conhecidas estão em [`PHASE5_SNAP_RESEARCH.md`](PHASE5_SNAP_RESEARCH.md). Os arquivos selecionados são baixados somente a partir dos URLs no manifesto; o script grava SHA-256 e tamanho do arquivo em `phase5_datasets.json`. Os arquivos `.txt.gz` ficam em `data/phase5_snap/`, ignorados pelo Git, e não devem ser redistribuídos com este repositório porque as fontes consultadas não publicam licença específica para esses dados.

```bash
python3 phase5_download_snap.py
python3 phase5_bench.py --out results/phase5/real_data --seeds 3 --repeats 2 --queries 1000 --batch-size 8
python3 phase5_temporal_bench.py --out results/phase5/temporal_history
python3 phase5_components_bench.py --out results/phase5/components
python3 phase5_synthetic_bench.py --out results/phase5/synthetic_30seeds
python3 phase5_plot.py
```

O benchmark real recusa sobrescrever uma pasta de resultados preenchida. Para uma nova execução, escolha outro `--out`. O benchmark temporal reconstrói estados anteriores a partir do log e não mantém snapshots no protótipo, embora retenha temporariamente cinco snapshots durante a comparação de memória.

O comparador NetworkX é opcional e fica fora das dependências do projeto. Para instalá-lo em ambiente separado:

```bash
python3 -m venv /tmp/aether-networkx-env
/tmp/aether-networkx-env/bin/python -m pip install networkx
/tmp/aether-networkx-env/bin/python phase5_networkx_bench.py --out results/phase5/networkx_reference
```

No Windows, use os equivalentes `.venv\Scripts\python.exe` e `pip`. O script verifica que o hash da carga gerada coincide com o benchmark AETHER principal e confere respostas com BFS independente. Ele cobre apenas datasets pequenos/médios selecionados; não altera `requirements.txt` nem é usado automaticamente pelo núcleo.

## Ambiente efetivamente medido

Esta execução ocorreu em Ubuntu 24.04.5 LTS, Linux aarch64, Python 3.12.3 e Rust stable 1.99.1, com 6 CPUs lógicas, aproximadamente 15 GiB de RAM total reportada e 13 GiB disponíveis antes da execução. Os resultados não incluem Windows 10/11. Não compare diretamente as latências da Fase 4: aquela medição usou host AMD EPYC x86_64 e workloads sintéticos, enquanto a Fase 5 desta tarefa usou ARM64 e dados SNAP reais.
