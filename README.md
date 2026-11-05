# AETHER

**AETHER é um protótipo experimental de grafos dinâmicos e raciocínio simbólico sobre fatos relacionais estruturados.** O repositório reúne implementações em Python, um backend opcional em Rust e harnesses reproduzíveis para avaliar algoritmos e políticas de raciocínio.

O projeto não é um sistema de inteligência geral, não afirma compreender linguagem natural e não deve ser tratado como mecanismo de decisão de produção. Resultados de desempenho são específicos aos workloads e ambientes documentados; cada relatório registra metodologia, limitações e proveniência.

## O que o projeto explora

- **Grafo mutável:** criação, remoção e consulta de arestas, com componentes, índices e variantes para workloads diferentes.
- **Conhecimento relacional:** entidades e fatos estruturados com proveniência, índices de consulta e identidade tipada dos valores escalares (`bool`, `int`, `float`, `str` e `None`).
- **Inferência simbólica:** encadeamento forward, backward e híbrido, regras versionadas, limites explícitos de execução e consultas com variáveis livres.
- **Explicabilidade e atualização:** conclusões podem conservar provas alternativas e referências aos fatos que as sustentam. Remoções ou mudanças de regras podem exigir recomputação completa; o sistema marca essa necessidade em vez de apresentar conclusões potencialmente obsoletas como completas.
- **Consistência declarativa:** contradições são avaliadas por regras de incompatibilidade explicitamente declaradas; fatos de fontes distintas não são apagados automaticamente.
- **Backend nativo opcional:** bindings `ctypes` para código Rust, compilado para o sistema e a arquitetura em uso quando solicitado. A implementação Python não depende da compilação Rust para ser importada.
- **Avaliação experimental:** benchmarks por fase, oráculos independentes, fixtures e resultados históricos para estudar comportamento e desempenho.

A [visão de arquitetura](docs/architecture/OVERVIEW.md), o [mapa de módulos](docs/architecture/MODULES.md) e o [grafo de dependências](docs/architecture/DEPENDENCIES.md) explicam as responsabilidades e fronteiras entre componentes.

## Estado do projeto

A organização do código instalável está em `src/aether/`; os benchmarks, testes, dados/manifestos, resultados e documentação ficam em diretórios próprios. A Phase 8 acrescenta identidade tipada, provas alternativas, consultas abertas, lifecycle de regras e índice Rust versionado. Seu [relatório técnico](docs/phases/PHASE8_REPORT.md) registra os detalhes e as ressalvas experimentais.

A matriz de CI cobre **Linux, macOS e Windows** com Python **3.10, 3.12 e 3.13**. A validação indicada para compatibilidade é sempre a execução real de CI associada ao commit relevante. A matriz não inclui Linux ARM64; não se deve inferir suporte validado para uma plataforma que não foi testada.

## Arquitetura do repositório

| Caminho | Responsabilidade |
|---|---|
| `src/aether/core/knowledge/` | Entidades, fatos, proveniência e armazenamento de conhecimento |
| `src/aether/reasoning/` | Inferência, regras, explicações, consistência e controladores |
| `src/aether/graph/` | Grafos dinâmicos, componentes, consultas e índices |
| `src/aether/memory/` | Cache, padrões e políticas de memória |
| `src/aether/temporal/` | Eventos, checkpoints e reconstrução temporal |
| `src/aether/native/` | Bindings nativos e fonte Rust da FFI |
| `src/aether/adapters/` | Adaptação de dados externos, incluindo proveniência SNAP |
| `benchmarks/` | Harnesses de benchmark organizados por fase |
| `tests/` | Testes unitários, integração, regressão, concorrência e portabilidade |
| `datasets/manifests/` | Manifestos versionados para localizar datasets externos |
| `results/` | Saídas históricas de experimentos; não são regeneradas pela CI |
| `docs/` | Guias, arquitetura, relatórios de fases e auditorias |

Shims top-level preservam temporariamente imports e comandos legados. Eles encaminham para a implementação canônica em `aether.*`; não são uma segunda cópia do domínio.

## Requisitos e instalação

O núcleo Python requer **Python 3.10 ou superior**. A instalação normal não compila nem exige Rust. O backend nativo opcional exige **Rust 1.99.1** (definido por `rust-toolchain.toml`) e um linker/runtime C compatível com o sistema operacional.

### Instalação editável para desenvolvimento

```bash
python -m venv .venv
# Linux/macOS:
source .venv/bin/activate
# Windows PowerShell:
# .\.venv\Scripts\Activate.ps1

python -m pip install --upgrade pip
python -m pip install -e .
python -c "import aether; print(aether.__version__)"
```

Extras opcionais:

```bash
python -m pip install ".[plots]"       # matplotlib e numpy para gráficos
python -m pip install ".[networkx]"     # comparador externo opcional
```

Consulte o [setup geral](docs/development/SETUP.md), os guias para [Windows](docs/development/SETUP_WINDOWS.md) e [Linux](docs/development/SETUP_LINUX.md), e o guia de [instalação e execução](docs/development/PHASE5_INSTALL.md). Para compilar o backend nativo explicitamente:

```bash
python -c "from aether.native.bindings import compile_native; print(compile_native())"
```

O wrapper seleciona `.dll`, `.so` ou `.dylib` conforme o host e verifica ABI/plataforma. **Não reutilize uma biblioteca nativa compilada para outro sistema operacional ou arquitetura.**

## Exemplo rápido

O exemplo abaixo cria um grafo e uma base de fatos, aplica uma regra e consulta as conclusões derivadas:

```python
from aether import DynamicGraph, KnowledgeStore
from aether.reasoning.inference import InferenceEngine, Pattern, Rule

# Grafo dinâmico
graph = DynamicGraph(3)
graph.add_edge(0, 1)
assert graph.has_edge(0, 1)

# Conhecimento relacional e regra: quem conhece alguém está conectado a essa pessoa.
store = KnowledgeStore()
store.add_entity("alice")
store.add_fact("alice", "knows", "bob")

rule = Rule(
    rule_id="knows-implies-connected",
    antecedents=(Pattern("?person", "knows", "?other"),),
    consequent=Pattern("?person", "connected_to", "?other"),
)
result = InferenceEngine(store, rules=[rule]).infer()
assert any(fact.key == ("alice", "connected_to", "bob") for fact in result.conclusions)
```

`KnowledgeStore` armazena fatos; `InferenceEngine` deriva conclusões de regras. A identidade de escalares é tipada: por exemplo, `True`, `1` e `1.0` são valores distintos para fins de fatos e consultas. Veja os testes em `tests/` para exemplos de proveniência, provas alternativas, consultas abertas, contradições e lifecycle de regras.

## Testes e validação

Com o pacote instalado em modo editável e a toolchain Rust disponível para os testes nativos:

```bash
python -m unittest discover -s tests -v
```

Para executar somente os testes de portabilidade:

```bash
python -m unittest discover -s tests/portability -v
```

A suíte verifica as APIs, a integração Rust, a equivalência com oráculos de referência e aspectos de compatibilidade entre plataformas. Consulte o [guia de testes](docs/development/TESTING.md). A ausência de Rust pode fazer com que testes que dependem do compilador nativo não executem seu caminho completo; isso não valida a FFI naquele ambiente.

## Benchmarks e datasets

Os scripts canônicos ficam em `benchmarks/` e podem ser chamados como módulos. Para ver parâmetros e escolher cargas pequenas antes de uma execução completa:

```bash
python -m benchmarks.baseline.aether_bench --help
python -m benchmarks.phase8.phase8_bench --help
```

Exemplo de smoke da Phase 8 (um workload/seed, resultados temporários):

```bash
python -m benchmarks.phase8.phase8_bench \
  --seeds 1 \
  --families contradictions \
  --out /tmp/aether-phase8-smoke
```

Para a configuração completa da Phase 8, consulte o [relatório e metodologia](docs/phases/PHASE8_REPORT.md). Os benchmarks devem usar diretórios `--out` novos; scripts que protegem resultados existentes recusam sobrescrever pastas preenchidas. Resultados antigos em `results/` são registros históricos e não comparações automaticamente reproduzíveis em outro host.

Datasets SNAP grandes **não são incluídos** no pacote. O manifesto versionado está em [`datasets/manifests/phase5_datasets.json`](datasets/manifests/phase5_datasets.json); consulte as condições e fontes antes de baixar os arquivos e confira os hashes registrados. Veja também o [guia de benchmarks](docs/development/BENCHMARKS.md). Medições que não estão disponíveis de forma confiável devem permanecer ausentes (`null`), não ser inventadas como zero. Proxies de operações não são FLOPs e não devem ser comparados como se medissem o mesmo trabalho entre algoritmos.

## Documentação adicional

- [Arquitetura](docs/architecture/OVERVIEW.md), [módulos](docs/architecture/MODULES.md) e [dependências](docs/architecture/DEPENDENCIES.md)
- [Relatórios de fases](docs/phases/) e [resultados históricos](results/)
- [Configuração do ambiente](docs/development/SETUP.md), [testes](docs/development/TESTING.md) e [benchmarks/datasets](docs/development/BENCHMARKS.md)
- [Auditoria inicial](docs/audits/REPOSITORY_REORGANIZATION_BASELINE.md) e [relatório de reorganização](docs/audits/REPOSITORY_REORGANIZATION_REPORT.md)

## Licença e segurança

O código é distribuído sob a licença [MIT](LICENSE). Para relatar vulnerabilidades de forma responsável, consulte [SECURITY.md](SECURITY.md).
