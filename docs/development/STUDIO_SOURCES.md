# Referências de implementação do Studio

React Flow fornece componentes `Controls`, `MiniMap`, `Background` e `Panel` para navegação/zoom e contexto do grafo: [documentação oficial](https://reactflow.dev/learn/concepts/built-in-components), consultada em 5 de novembro de 2026. O tema dark e as variáveis CSS permitem preservar a identidade visual grafite/ciano: [Theming](https://reactflow.dev/learn/customization/theming). O frontend usa componentes e ícones vetoriais da biblioteca, sem ilustrações decorativas ou gráficos de dados inventados.

A autenticação do ambiente gerenciado usa Manus OAuth e o cookie `webdev_app_session`, com validação JWT HS256, expiry e appId no servidor. Auto-login do Preview é aceito somente após validação e autorização do openId. Instalações independentes podem usar token local de operador definido pelo administrador; o token não é embutido no frontend e não habilita bypass de autenticação.
