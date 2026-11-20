# AGENTS.md - Diretrizes Operacionais de Desenvolvimento

Voce atua como engenheiro de software principal na construcao do projeto **Cathedra**. Antes de implementar qualquer funcionalidade, leia `docs/SPEC.md` e os demais documentos em `docs/` para verificar os contratos de dados e a arquitetura do pipeline.

## 1. Stack tecnologica e ambiente
- **Linguagem:** Python 3.12+
- **Gerenciador de pacotes e ambiente:** `uv` (nunca use `pip` ou `poetry` diretamente)
- **Validacao e configuracao:** `pydantic` v2 e `pydantic-settings`
- **Extracao de documentos:** `docling` ou `pymupdf4llm` para PDFs; `python-pptx` para apresentacoes
- **Qualidade de codigo:** `ruff` (lint e formatacao), `mypy` (tipagem estrita) e `pytest`

## 2. Comandos essenciais
- Instalar dependencias: `uv sync`
- Adicionar pacote: `uv add <pacote>`
- Executar aplicacao via CLI: `uv run cathedra <comando>`
- Rodar bateria de testes: `uv run pytest -v`
- Checar formatacao e lint: `uv run ruff check . && uv run ruff format --check .`
- Checar tipagem estatica: `uv run mypy src/`

## 3. Estrutura do repositorio de codigo
Mantenha a separacao estrita de responsabilidades dentro de `src/cathedra/`:

```text
src/cathedra/
├── cli.py                 # Ponto de entrada CLI (Typer)
├── config.py              # Variaveis de ambiente e caminhos do Vault (pydantic-settings)
├── schemas.py             # Contratos de dados definidos em docs/SPEC.md
├── ingestion/
│   ├── syllabus_parser.py # Converte o Programa do Curso em JSON estruturado
│   └── slide_parser.py    # Extrai texto, tabelas e LaTeX dos slides
├── agents/
│   ├── prompts/           # Prompts de sistema isolados em arquivos .md (fact_checker.md, humanizer.md, drafter.md)
│   ├── graph.py           # Definicao do fluxo de estados do pipeline
│   └── validators.py      # Linter deterministico em Python para regras do humanizer-ptbr
└── exporters/
    └── obsidian_writer.py # Escrita idempotente de paginas Wiki, MOCs e Zettels
4. Regras inegociaveis de engenharia
Zero prompts hardcoded no Python: Todo prompt de sistema e instrucao de skill (fact-check e humanizer-ptbr) deve residir em src/cathedra/agents/prompts/*.md e ser carregado dinamicamente.

Validacao hibrida no Humanizer: Nao confie apenas no prompt para cumprir a skill humanizer-ptbr. O modulo validators.py (especificado em docs/LINTER_RULES.md) deve inspecionar o texto retornado pela LLM via expressoes regulares para barrar travessoes explicativos (— ou –), paragrafos com mais de 4 frases e termos da lista negra antes de aprovar o estado.

Rastreabilidade no Fact-Check: O no de checagem de fatos nunca deve alterar o texto silenciosamente sem antes registrar o veredito (S1 a S6) no arquivo JSON de auditoria factual.

Idempotencia no Obsidian: Reprocessar o mesmo slide de aula deve atualizar a pagina Aula_XX_Tema.md e o indice _Indice_Materia.md sem duplicar links nos MOCs nem sobrescrever notas manuais adicionadas pelo usuario fora das tags delimitadoras (ver docs/TEMPLATES_OBSIDIAN.md).

Tipagem completa: Todas as funcoes devem possuir type hints nos parametros e no retorno. Dicionarios genericos (dict[str, Any]) sao proibidos na passagem de estado entre nos do pipeline; use os modelos de schemas.py.

5. Protocolo de execucao passo a passo (One-Task Loop)
Voce esta proibido de implementar multiplas etapas em uma unica resposta. Siga esta sequencia em todas as interacoes:

Leitura de Estado: Ao iniciar, leia docs/PLAN.md e identifique a primeira etapa marcada com [ ]. Se o usuario nao especificar outra tarefa, assuma essa etapa como seu unico escopo atual.

Confirmacao de Escopo: Antes de escrever codigo complexo, liste em 3 linhas quais arquivos serao criados ou alterados naquela etapa especifica e qual contrato do docs/SPEC.md sera atendido.

Desenvolvimento Orientado a Testes (TDD): Escreva primeiro os testes unitarios da etapa usando fixtures locais (nunca dependa de chamadas reais de API para passar no pytest).

Verificacao Tripla Obrigatoria: Apos implementar o codigo da etapa, execute no terminal:

uv run pytest -v

uv run ruff check . && uv run ruff format --check .

uv run mypy src/

Atualizacao de Estado e Trava de Parada (STOP GATE): Quando os tres comandos passarem com zero erros, marque a etapa como [x] em docs/PLAN.md, apresente um resumo tecnico curto do que foi entregue e PARE IMEDIATAMENTE. Aguarde a revisao e o git commit do usuario antes de iniciar a proxima etapa da fila.