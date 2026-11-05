# Plataforma AETHER

A plataforma organiza três camadas independentes: núcleo Python/Rust, API FastAPI e cliente React/TypeScript/Vite. O núcleo continua importável sem FastAPI, Node ou React. A API usa os componentes existentes; a interface consome REST em `/api/v1` e notificações em `/ws`, sem reproduzir o motor no browser.

## Núcleo e estado

`KnowledgeStore` mantém entidades, valores escalares tipados, fatos explícitos, evidências e índices. As conclusões derivadas e suas provas pertencem ao motor de raciocínio. A API compõe `KnowledgeReasoner` para mutações incrementais e recomputação segura, e oferece estratégias forward/backward/híbrida/adaptativa sem esconder limites de completude. A regra de consulta não é um trecho Python executável.

A memória operacional é separada do conhecimento: `AdaptiveMemory` contém bytes de cache e tiers de acesso sob orçamento residente, com cold tier SQLite. `IncrementalPatternLearner` conta operações e transições observáveis; esses contadores não criam fatos semânticos. Métricas do processo e histórico de desempenho são amostras retidas por limite, não uma série inventada.

`EventEngine` é uma fila/log SQLite com IDs deduplicados, ordem de sequência, backpressure, retries, claims e checkpoints. `KnowledgeEventProcessor` integra eventos às mutações do Reasoner. O contrato é at-least-once: handlers precisam ser idempotentes; snapshot e ack não formam transação distribuída. Veja [Event Engine](EVENT_ENGINE.md).

O backend Rust permanece opcional e separado da instalação Python. A biblioteca FFI é compilada para o sistema/arquitetura corrente; `.dll`, `.so` e `.dylib` não são intercambiáveis. O Studio não presume que Rust está ativo: status e contadores dependem de verificações/operações reais. A otimização medida de joins segue configurável e não é promovida automaticamente a padrão; veja [Eficiência](EFFICIENCY.md).

## API e cliente

A API mantém uma instância de estado por processo, serializa mutações compartilhadas e valida todas as entradas. Estado explícito, regras/configuração, memória operacional e eventos têm persistências distintas. Reiniciar não deve recuperar conclusões antigas sem recomputar pelas regras atuais. Caminhos de arquivos e código executável não são aceitos nas configurações remotas.

O cliente mantém componentes/rotas próprias em `frontend/`, com serviços de HTTP, hooks de carregamento/notificações e módulos de Dashboard, Knowledge, Reasoning, Memory, Events e Monitoring. Grafo interativo usa React Flow; dados e relações vêm da API. Quando uma notificação WebSocket chega, páginas relevantes invalidam/refazem leituras; a conexão não concede autorização para executar operações.

## Segurança e limites operacionais

Autenticação é exigida também em desenvolvimento acessível pela rede. Ambiente Manus usa OAuth e valida o JWT/cookie do projeto. Identidade autenticada não basta para escrever: a aplicação resolve o papel, e operadores devem ser explicitamente autorizados no servidor. Instalação independente pode usar token de operador configurado pelo administrador, trocado por sessão HttpOnly; o frontend não armazena segredos. Mutações exigem CSRF; CORS e Origin de WebSocket são restritos. HTTPS Preview usa cookies `Secure; SameSite=None`; HTTP local segue configuração separada.

A execução suportada nesta entrega é um único worker Uvicorn por diretório de dados. Múltiplos workers/processos compartilhando o snapshot em memória não formam um cluster consistente. O Event Engine tem concorrência serializada para preservar ordem, não throughput paralelo ilimitado. Dados de containers/publicação são efêmeros; não publique esta composição local como serviço durável sem substituir persistência e revisar o modelo de acesso. A branch GitHub é a entrega de código; Preview não é confirmação de publicação pública.

## Operação

Instale o extra Python da API, dependências lockfile do frontend e execute o launcher local. Scripts shell e PowerShell delegam a `scripts/run_studio.py`, que usa paths relativos ao checkout e encerra os filhos no Ctrl+C. Para detalhes, consulte [Windows](../development/SETUP_WINDOWS.md), [Linux](../development/SETUP_LINUX.md), [Studio](../development/WEB_STUDIO.md) e [API](API.md). Testes de plataforma devem ser citados por execução efetiva, não apenas pela existência de scripts ou matriz CI.
