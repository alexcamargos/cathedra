# Plano de Execucao Passo a Passo (Backlog Atomico)

Este arquivo controla o estado atual do desenvolvimento. O agente deve executar **apenas uma etapa por vez**, validar com os comandos de aceite e marcar `[x]` antes de encerrar o turno.

---

## Etapa 01: Bootstrap do repositorio e configuracao base
- **Status:** `[x]`
- **Escopo:** Configurar `pyproject.toml` com `uv`, criar a arvore de diretorios em `src/mba_wiki/` e `tests/`, e implementar `src/mba_wiki/config.py` usando `pydantic-settings` (caminhos do Obsidian Vault e chaves de API).
- **Arquivos afetados:** `pyproject.toml`, `src/mba_wiki/__init__.py`, `src/mba_wiki/config.py`, `tests/test_config.py`.
- **Criterio de aceite:** `uv run pytest tests/test_config.py` e `uv run mypy src/` passando sem erros.

## Etapa 02: Contratos de dados em Pydantic
- **Status:** `[x]`
- **Escopo:** Implementar todos os modelos definidos na secao 3 do `docs/SPEC.md` (`SyllabusModule`, `StructuredSyllabus`, `SlideChunk`, `ClaimAuditItem`, `AtomicZettel`, `WikiLessonOutput`, `LessonAuditReport`, `LessonPipelineState`).
- **Arquivos afetados:** `src/mba_wiki/schemas.py`, `tests/test_schemas.py`.
- **Criterio de aceite:** Testes unitarios validando instanciacao correta e rejeicao de tipos invalidos (`ValidationError`) com `uv run pytest tests/test_schemas.py`.

## Etapa 03: Criacao de fixtures estaticas e protocolo de mock do LLM
- **Status:** `[x]`
- **Escopo:** Implementar o protocolo `StructuredLLMClient` em `src/mba_wiki/agents/llm_client.py` conforme `docs/INTEGRATIONS.md` e criar massa de dados estatica e fixture `FakeLLMClient` para testes deterministicos sem gastar tokens de LLM. Incluir trecho de ementa em texto, JSON de slides extraidos com LaTeX e texto em portugues com vicios propositais de IA.
- **Arquivos afetados:** `src/mba_wiki/agents/llm_client.py`, `tests/conftest.py`, `tests/fixtures/sample_syllabus.txt`, `tests/fixtures/sample_slides.json`, `tests/fixtures/bad_ai_prose.md`.
- **Criterio de aceite:** Fixtures e `FakeLLMClient` carregando e passando em testes via `pytest` em `tests/conftest.py`.

## Etapa 04: Linter deterministico do Humanizer (100% Python)
- **Status:** `[x]`
- **Escopo:** Implementar `src/mba_wiki/agents/validators.py` com base em `docs/LINTER_RULES.md`. O modulo analisa Markdown e retorna violacoes caso encontre travessoes explicativos, emojis, setas, paragrafos acima de 4 frases ou termos da lista negra.
- **Arquivos afetados:** `src/mba_wiki/agents/validators.py`, `tests/test_validators.py`.
- **Criterio de aceite:** O validador reprova `bad_ai_prose.md` apontando falhas e aprova texto limpo em `uv run pytest tests/test_validators.py`.

## Etapa 05: Parser do Programa do Curso (Ementa)
- **Status:** `[x]`
- **Escopo:** Implementar `src/mba_wiki/ingestion/syllabus_parser.py` para ler o documento do Programa do Curso, estruturar as disciplinas via LLM e salvar o `ementa_estruturada.json` validado.
- **Arquivos afetados:** `src/mba_wiki/ingestion/syllabus_parser.py`, `tests/test_syllabus_parser.py`.
- **Criterio de aceite:** Teste unitario com mock convertendo `sample_syllabus.txt` em lista valida de `SyllabusModule`.

## Etapa 06: Extrator estrutural de slides
- **Status:** `[x]`
- **Escopo:** Implementar `src/mba_wiki/ingestion/slide_parser.py` para ler PDF/PPTX, extrair texto slide a slide, preservar tabelas em Markdown e isolar formulas em LaTeX, retornando `SlideChunk`.
- **Arquivos afetados:** `src/mba_wiki/ingestion/slide_parser.py`, `tests/test_slide_parser.py`.
- **Criterio de aceite:** Extracao testada sobre PDF/PPTX minimo, retornando objetos `SlideChunk` validos.

## Etapa 07: Agente redator e decompositor (Drafter Node)
- **Status:** `[x]`
- **Escopo:** Criar o prompt `src/mba_wiki/agents/prompts/drafter.md` e o modulo `src/mba_wiki/agents/drafter.py`. Recebe `SlideChunk` e `SyllabusModule`, gerando o rascunho da aula para a Wiki e os candidatos a `AtomicZettel`.
- **Arquivos afetados:** `src/mba_wiki/agents/prompts/drafter.md`, `src/mba_wiki/agents/drafter.py`, `tests/test_drafter.py`.
- **Criterio de aceite:** Teste com cliente LLM mockado garantindo aderencia aos schemas.

## Etapa 08: Agente auditor de fatos (Fact-Check Node)
- **Status:** `[x]`
- **Escopo:** Portar as regras da skill `fact-check` para `src/mba_wiki/agents/prompts/fact_checker.md` e implementar `src/mba_wiki/agents/fact_checker.py`. Extrai afirmacoes, confronta com slides e fontes, remove afirmacoes sem lastro (`S4`) e corrige erros materiais (`S1`/`S2`), gerando `ClaimAuditItem`.
- **Arquivos afetados:** `src/mba_wiki/agents/prompts/fact_checker.md`, `src/mba_wiki/agents/fact_checker.py`, `tests/test_fact_checker.py`.
- **Criterio de aceite:** Teste validando que afirmacao `unsupported` (`S4`) dispara remocao no texto e registro no log.

## Etapa 09: Agente de polimento estilistico com loop de retentativa (Humanizer Node)
- **Status:** `[x]`
- **Escopo:** Portar a skill `humanizer-ptbr` para `src/mba_wiki/agents/prompts/humanizer.md` e implementar `src/mba_wiki/agents/humanizer.py`. Apos reescrita, o texto passa pelo `validators.py` (Etapa 04). Se houver violacoes, realimenta o erro para a LLM corrigir (maximo 3 tentativas).
- **Arquivos afetados:** `src/mba_wiki/agents/prompts/humanizer.md`, `src/mba_wiki/agents/humanizer.py`, `tests/test_humanizer.py`.
- **Criterio de aceite:** Teste simulando resposta inicial com travessao, comprovando interceptacao e acionamento corretivo.

## Etapa 10: Orquestracao do pipeline completo
- **Status:** `[x]`
- **Escopo:** Implementar `src/mba_wiki/agents/graph.py` conectando ingestao, Drafter, Fact-Checker e Humanizer em fluxo de estado tipado que devolve `WikiLessonOutput`.
- **Arquivos afetados:** `src/mba_wiki/agents/graph.py`, `tests/test_graph.py`.
- **Criterio de aceite:** Teste ponta a ponta (com mocks) executando transicao completa.

## Etapa 11: Exportador idempotente para o Obsidian
- **Status:** `[x]`
- **Escopo:** Implementar `src/mba_wiki/exporters/obsidian_writer.py` para criacao/atualizacao da pagina da aula, atualizacao sem duplicatas do `_Indice_Materia.md`, gravacao de Zettels e persistencia do JSON de auditoria, seguindo `docs/TEMPLATES_OBSIDIAN.md`.
- **Arquivos afetados:** `src/mba_wiki/exporters/obsidian_writer.py`, `tests/test_exporters.py`.
- **Criterio de aceite:** Teste com `tmp_path` provando que rodar o exportador duas vezes nao duplica links no indice.

## Etapa 12: Interface de linha de comando (CLI)
- **Status:** `[x]`
- **Escopo:** Implementar `src/mba_wiki/cli.py` com comandos `init-syllabus <arquivo>` e `build-lesson <slide_path> --discipline <slug> --lesson <numero>`.
- **Arquivos afetados:** `src/mba_wiki/cli.py`, `tests/test_cli.py`.
- **Criterio de aceite:** Execucao via `CliRunner` passando em `pytest`, `ruff` e `mypy`.