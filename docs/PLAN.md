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


## Etapa 13: Contratos de dados para conexoes transversais e diario de tensoes
- **Status:** `[x]`
- **Escopo:** Implementar os modelos `CrossDisciplineLink` e `DialecticalTension` em `src/mba_wiki/schemas.py`, estendendo `DraftResult`, `WikiLessonOutput` e `LessonPipelineState` com colecoes default_factory=list para assegurar retrocompatibilidade.
- **Arquivos afetados:** `src/mba_wiki/schemas.py`, `tests/test_schemas.py`.
- **Criterio de aceite:** Testes unitarios validando instanciacao, validacoes de campo, tipos literais e retrocompatibilidade com `uv run pytest tests/test_schemas.py`.

## Etapa 14: Prompt do drafter e injecao curricular global de tensoes
- **Status:** `[x]`
- **Escopo:** Atualizar `src/mba_wiki/agents/prompts/drafter.md` e `src/mba_wiki/agents/drafter.py` para injetar contexto sumarizado de `StructuredSyllabus` e extrair conexoes transversais e tensoes dialeticas no `DraftResult`.
- **Arquivos afetados:** `src/mba_wiki/agents/prompts/drafter.md`, `src/mba_wiki/agents/drafter.py`, `tests/test_drafter.py`.
- **Criterio de aceite:** Testes unitarios com cliente LLM mockado validando preenchimento de `cross_links` e `detected_tensions`.

## Etapa 15: Exportador idempotente para o diario de tensoes no Obsidian
- **Status:** `[x]`
- **Escopo:** Estender `src/mba_wiki/exporters/obsidian_writer.py` para gerar notas em `04_Diario_Tensoes/<tension_slug>.md` e o indice `04_Diario_Tensoes/_Indice_Tensoes.md`, garantindo acumulacao idempotente de evidencias entre aulas e preservacao de notas pessoais.
- **Arquivos afetados:** `src/mba_wiki/exporters/obsidian_writer.py`, `tests/test_exporters.py`.
- **Criterio de aceite:** Testes com `tmp_path` simulando duas aulas alimentando a mesma tensao sem duplicar entradas nem apagar anotacoes manuais.

## Etapa 16: Orquestracao do grafo e comando CLI para consolidacao de tensoes
- **Status:** `[x]`
- **Escopo:** Integrar a passagem do `StructuredSyllabus` ao drafter em `src/mba_wiki/agents/graph.py` e persistencia de tensoes em `build-lesson`. Implementar o comando `sync-tensions` em `src/mba_wiki/cli.py` para reindexacao do Vault.
- **Arquivos afetados:** `src/mba_wiki/agents/graph.py`, `src/mba_wiki/cli.py`, `tests/test_graph.py`, `tests/test_cli.py`.
- **Criterio de aceite:** Pipeline ponta a ponta e testes de CLI passando em `pytest`, `ruff` e `mypy`.

---

## Etapa 17: Blindagem deterministica de exclusao e correcao factual no Fact-Checker
- **Status:** `[x]`
- **Escopo:** Blindar `apply_audit_remediations` em `src/mba_wiki/agents/fact_checker.py`: (1) garantir que afirmacoes `unsupported` (`S4`) e correcoes `S2` que nao foram localizadas e substituidas no texto marquem `has_unresolved_blockers = True`; (2) implementar casamento difuso/normalizado de sentencas para tolerar pequenas variacoes de citacao da LLM sem deixar alucinacoes passarem.
- **Arquivos afetados:** `src/mba_wiki/agents/fact_checker.py`, `tests/test_fact_checker.py`.
- **Criterio de aceite:** Testes unitarios cobrindo citacoes com pequenas variacoes e assercoes de bloqueio passando com `uv run pytest tests/test_fact_checker.py`, `uv run ruff check .` e `uv run mypy src/`.

## Etapa 18: Auditoria factual de Zettels atomicos e Tensoes dialeticas no grafo
- **Status:** `[x]`
- **Escopo:** Integrar a verificacao de `extracted_zettels` e `detected_tensions` ao pipeline factual em `src/mba_wiki/agents/fact_checker.py` e `src/mba_wiki/agents/graph.py`. Se um zettel ou tensao contiver afirmacoes falsas (`S1`) ou sem suporte (`S4`), expurgar o item corrompido ou barrar a aprovacao do estado antes de persistir no cofre permanente.
- **Arquivos afetados:** `src/mba_wiki/agents/fact_checker.py`, `src/mba_wiki/agents/graph.py`, `src/mba_wiki/schemas.py`, `tests/test_fact_checker.py`, `tests/test_graph.py`.
- **Criterio de aceite:** Testes ponta a ponta garantindo que zettels/tensoes com alucinacoes nao cheguem a `WikiLessonOutput` passando com `uv run pytest tests/test_fact_checker.py tests/test_graph.py`, `uv run ruff check .` e `uv run mypy src/`.

## Etapa 19: Migracao do transporte do AGYCLIClient para stdin e mitigacao de limite no Windows
- **Status:** `[x]`
- **Escopo:** Refatorar `AGYCLIClient._execute_cli` em `src/mba_wiki/agents/llm_client.py` para alimentar o processo via `stdin` (pipe UTF-8) ou arquivo temporario em `scratch/` quando o prompt for volumoso, contornando o limite de 32 KB da API Win32. Implementar extracao resiliente do JSON via busca do envelope delimitador `{...}`.
- **Arquivos afetados:** `src/mba_wiki/agents/llm_client.py`, `tests/test_agy_client.py`.
- **Criterio de aceite:** Testes unitarios simulando prompts extensos e outputs com logs preliminares passando com `uv run pytest tests/test_agy_client.py`, `uv run ruff check .` e `uv run mypy src/`.

## Etapa 20: Robustez do Humanizer contra loops N+1 e protecao de cercas de codigo
- **Status:** `[x]`
- **Escopo:** Ajustar `strip_markdown_fences` em `src/mba_wiki/agents/humanizer.py` para proteger blocos de codigo Markdown finais legitimate. Implementar sanitizacao preliminar deterministica em Python para zettels antes de invocar a LLM, prevenindo a multiplicacao de chamadas sequenciais (N+1).
- **Arquivos afetados:** `src/mba_wiki/agents/humanizer.py`, `tests/test_humanizer.py`.
- **Criterio de aceite:** Testes validando preservacao de blocos de codigo e reducao de retentativas passando com `uv run pytest tests/test_humanizer.py`, `uv run ruff check .` e `uv run mypy src/`.

## Etapa 21: Roteamento de modelo de auditoria na CLI e auto-recuperacao de delimitadores no Obsidian
- **Status:** `[x]`
- **Escopo:** Atualizar `src/mba_wiki/cli.py` para honrar `llm_model_auditor` injetando cliente com modelo especializado no auditor. Adicionar a flag `--force` na CLI e rotina de auto-reparo de delimitadores em `src/mba_wiki/exporters/obsidian_writer.py` para restaurar arquivos com tags corrompidas sem descartar anotacoes pessoais.
- **Arquivos afetados:** `src/mba_wiki/cli.py`, `src/mba_wiki/exporters/obsidian_writer.py`, `tests/test_cli.py`, `tests/test_exporters.py`.
- **Criterio de aceite:** Testes com CLI Runner e reprocessamento com delimitadores rompidos passando com `uv run pytest tests/test_cli.py tests/test_exporters.py`, `uv run ruff check .` e `uv run mypy src/`.

---

## Etapa 22: Contratos de dados para transcricao e modelos Pydantic
- **Status:** `[x]`
- **Escopo:** Implementar `TranscriptSegment` e `VideoTranscript` em `src/mba_wiki/schemas.py` de acordo com `docs/TRANSCRIPTION_SPEC.md`, garantindo validacao de intervalos de tempo, tipagem estrita e serializacao JSON estruturada.
- **Arquivos afetados:** `src/mba_wiki/schemas.py`, `tests/test_schemas.py`.
- **Criterio de aceite:** Testes unitarios cobrindo criacao valida, rejeicao de timestamps invalidos e serializacao passando em `uv run pytest tests/test_schemas.py`.

## Etapa 23: Auto-provisao de ambiente (FFmpeg e DLLs CUDA no Windows)
- **Status:** `[x]`
- **Escopo:** Implementar `src/mba_wiki/transcription/bootstrap.py` para verificar e provisionar dependencias de baixo nivel sem intervencao do usuario: auto-download/extracao do executavel estatico do FFmpeg para `%LOCALAPPDATA%\cathedra\bin` se ausente no sistema, adicao ao PATH dinamico, registro de diretorios de DLL NVIDIA (`nvidia-cublas-cu12`, `nvidia-cudnn-cu12`) via `os.add_dll_directory` no Windows e diagnostico de suporte CUDA.
- **Arquivos afetados:** `src/mba_wiki/transcription/bootstrap.py`, `src/mba_wiki/transcription/__init__.py`, `tests/test_bootstrap.py`.
- **Criterio de aceite:** Testes unitarios com mocks de download e checagem de binarios passando em `uv run pytest tests/test_bootstrap.py`, `uv run ruff check .` e `uv run mypy src/`.

## Etapa 24: Extrator de audio desacoplado com FFmpeg
- **Status:** `[x]`
- **Escopo:** Implementar `src/mba_wiki/transcription/audio_extractor.py` para extrair trilhas de audio de arquivos MP4 convertendo para PCM 16kHz mono WAV em diretorio temporario isolado, com tratamento de erros de codec e rotina de limpeza automatica do arquivo gerado via context manager.
- **Arquivos afetados:** `src/mba_wiki/transcription/audio_extractor.py`, `tests/test_audio_extractor.py`.
- **Criterio de aceite:** Testes unitarios mockando execucao de subprocesso do FFmpeg e validando parametros de comando (`-ar 16000`, `-ac 1`, `-vn`) passando em `uv run pytest tests/test_audio_extractor.py`.

## Etapa 25: Normalizador deterministico de vicios de fala e disfluencias
- **Status:** `[x]`
- **Escopo:** Implementar `src/mba_wiki/transcription/cleaner.py` contendo expressoes regulares compiladas e regras lexicas para saneamento de oratoria academica em portugues (remocao de hesitacoes como "e...", "ah...", "hum...", muletas discursivas como "ne?", "tipo assim", e repeticoes imediatas de artigos/conectivos), preservando estritamente jargoes e termos tecnicos.
- **Arquivos afetados:** `src/mba_wiki/transcription/cleaner.py`, `tests/test_cleaner.py`.
- **Criterio de aceite:** Bateria de testes unitarios com frases tipicas de aula comprovando saneamento sem adulteracao de substancia conceitual em `uv run pytest tests/test_cleaner.py`.

## Etapa 26: Motor de transcricao com faster-whisper e suporte a CUDA
- **Status:** `[x]`
- **Escopo:** Implementar `src/mba_wiki/transcription/transcriber.py` encapsulando `faster-whisper.WhisperModel`. O modulo deve configurar modelo `large-v3`, quantizacao `int8_float16` (com fallback CPU em `int8`), filtro de voz Silero VAD ativado e retorno de lista tipada de `TranscriptSegment` pareada com o normalizador da Etapa 25.
- **Arquivos afetados:** `src/mba_wiki/transcription/transcriber.py`, `tests/test_transcriber.py`.
- **Criterio de aceite:** Testes unitarios com mock de WhisperModel comprovando construcao correta de segmentos e integracao com o cleaner em `uv run pytest tests/test_transcriber.py`.

## Etapa 27: Executor de lote com checkpoint/resume e persistencia estruturada
- **Status:** `[x]`
- **Escopo:** Implementar `src/mba_wiki/transcription/batch_runner.py` para varredura recursiva de diretorios de video, identificando subpastas por disciplina, ignorando videos com transcricoes validas ja presentes no destino (`data/raw/transcripts/`), gravando o JSON `VideoTranscript` de forma atomica e exibindo telemetria de execucao.
- **Arquivos afetados:** `src/mba_wiki/transcription/batch_runner.py`, `tests/test_batch_runner.py`.
- **Criterio de aceite:** Testes unitarios simulando lote de videos em `tmp_path`, verificando que arquivos ja transcritos sao pulados e novos sao persistidos em `uv run pytest tests/test_batch_runner.py`.

## Etapa 28: Interface CLI utilitaria para transcricao desacoplada
- **Status:** `[x]`
- **Escopo:** Integrar o comando `transcribe-batch` na CLI Typer (`src/mba_wiki/cli.py`), aceitando pasta de entrada de videos, pasta de saida, modelo e dispositivo como parametros opcionais, permitindo disparo autonomo e operacao noturna.
- **Arquivos afetados:** `src/mba_wiki/cli.py`, `tests/test_cli.py`.
- **Criterio de aceite:** Testes com `CliRunner` validando invocacao do comando e tratamento de argumentos em `uv run pytest tests/test_cli.py`.

---

## Etapa 29: Ingestao multimodal (Slides + Fala) e fusao contextual no Drafter e Fact-Checker
- **Status:** `[x]`
- **Escopo:** Integrar `VideoTranscript` no pipeline central: (1) adicionar `transcript` opcional ao `LessonPipelineState` e `ingestion_node`/`run_lesson_pipeline`; (2) atualizar `drafter.py` e `drafter.md` para fundir os tópicos do slide com a fala real do professor; (3) atualizar `fact_checker.py` e `fact_checker.md` para considerar a fala transcrita como lastro factual primário; (4) adicionar opção `--transcript` / `-t` com auto-detecção em `build-lesson` na CLI.
- **Arquivos afetados:** `src/mba_wiki/schemas.py`, `src/mba_wiki/agents/graph.py`, `src/mba_wiki/agents/drafter.py`, `src/mba_wiki/agents/prompts/drafter.md`, `src/mba_wiki/agents/fact_checker.py`, `src/mba_wiki/agents/prompts/fact_checker.md`, `src/mba_wiki/cli.py`, `tests/test_graph.py`, `tests/test_drafter.py`, `tests/test_fact_checker.py`, `tests/test_cli.py`.
- **Criterio de aceite:** Testes unitários comprovando que a presença da transcrição enriquece o rascunho sem alucinações e valida alegações factuais passando em `pytest`, `ruff` e `mypy`.

---

## Etapa 30: Telemetria estruturada, feedback em tempo real e resolucao hierarquica de disciplinas na transcricao
- **Status:** `[x]`
- **Escopo:** (1) Implementar `src/mba_wiki/transcription/telemetry.py` para registro detalhado de métricas (tempos de FFmpeg e Faster-Whisper, fatores de aceleração, palavras, bytes e status em JSONL e arquivo de log formatado); (2) Aprimorar `discover_lecture_videos` e normalização ASCII de slugs em `src/mba_wiki/transcription/batch_runner.py` para mapear corretamente a hierarquia Módulo -> Disciplina e suportar callback de progresso em tempo real; (3) Configurar codificação UTF-8 no Windows e feedback visual no comando CLI `transcribe-batch` com progresso [X/Total], detalhes do vídeo, ETA e estatísticas consolidadas; (4) Criar rotina para preservar e migrar transcrições prévias para os novos diretórios normalizados de disciplina.
- **Arquivos afetados:** `src/mba_wiki/transcription/telemetry.py`, `src/mba_wiki/transcription/batch_runner.py`, `src/mba_wiki/cli.py`, `tests/test_telemetry.py`, `tests/test_batch_runner.py`, `tests/test_cli.py`.
- **Criterio de aceite:** Testes unitários cobrindo telemetria, eventos de progresso e resolução hierárquica passando com `uv run pytest tests/test_telemetry.py tests/test_batch_runner.py tests/test_cli.py`, `uv run ruff check .` e `uv run mypy src/`.

## Etapa 31: Bloqueio de publicacao diante de pendencias factuais
- **Status:** `[x]`
- **Escopo:** Interromper o pipeline antes do humanizador quando houver bloqueadores factuais; registrar a auditoria em area separada de pendentes, preservar publicacoes anteriores e impedir a exportacao direta de resultados reprovados, inclusive com `--force`.
- **Arquivos afetados:** `src/mba_wiki/agents/graph.py`, `src/mba_wiki/cli.py`, `src/mba_wiki/exporters/obsidian_writer.py`, `tests/test_graph.py`, `tests/test_cli.py`, `tests/test_exporters.py`, `tests/test_config.py`, `docs/SPEC.md`, `README.md`.
- **Criterio de aceite:** `uv run pytest -v`, `uv run ruff check .`, `uv run ruff format --check .` e `uv run mypy src/` sem erros.

## Etapa 32: Auditoria factual apos o humanizador
- **Status:** `[x]`
- **Escopo:** Auditar novamente o corpo e os Zettels finais e as tensoes antes da publicacao, registrar os vereditos das duas etapas e bloquear a publicacao diante de qualquer desvio apontado ou falha do auditor final.
- **Arquivos afetados:** `src/mba_wiki/agents/graph.py`, `src/mba_wiki/schemas.py`, `tests/test_graph.py`, `tests/test_cli.py`, `docs/SPEC.md`, `README.md`.
- **Criterio de aceite:** `uv run pytest -v`, `uv run ruff check .`, `uv run ruff format --check .` e `uv run mypy src/` sem erros.
