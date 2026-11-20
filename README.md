# MBA Wiki Engine

Motor CLI em Python para geracao automatizada e idempotente de uma Wiki academica estruturada no Obsidian Vault, processando ementas oficiais, slides de aula e transcricoes literais de videoaulas.

## Visao Geral

O projeto resolve a fragmentacao semantica e a compressao conceitual tipicas de slides academicos. A partir dos objetivos curriculares da ementa e da exposicao oral do professor, o pipeline:
1. Converte ementas em modelos estruturados de dados (`SyllabusModule`).
2. Transcreve videoaulas em lote com aceleracao CUDA (`faster-whisper`), removendo disfluencias orais com saneamento lexico em portugues do Brasil.
3. Extrai texto, tabelas e equacoes em LaTeX de slides PDF ou PPTX.
4. Gera capitulos continuos da aula em prosa didatica e extrai conceitos universais para notas atomicas no Zettelkasten.
5. Mapeia tensoes dialeticas interdisciplinares e conexoes transversais com o curriculo global.
6. Submete o conteudo a auditoria factual adversarial (`fact-check`), corrigindo erros materiais e purgando afirmacoes sem respaldo.
7. Aplica linter estilistico estrito (`humanizer-ptbr`) com loop de autocorrecao para expurgar cliches e vicios sintaticos de IA.
8. Persiste os artefatos no Obsidian preservando anotacoes pessoais e auto-recuperando delimitadores estruturais.

## Arquitetura do Sistema

```text
[Videoaulas MP4] ──> [transcribe-batch] ──> data/raw/transcripts/ (*.json)
                                                         │
[Slides PDF/PPTX] ──> [slide_parser] ─────┐              │ (opcional)
                                          ▼              ▼
[Ementa Oficial]  ──> [syllabus_parser] ─> [Grafo do Pipeline]
                                                 │
                   ┌─────────────────────────────┼─────────────────────────────┐
                   ▼                             ▼                             ▼
           [Drafter Node]              [Fact-Checker Node]            [Humanizer Node]
        (Capitulo + Zettels +         (Auditoria de Fatos,          (Linter Estilistico,
          Tensoes Dialeticas)           Zettels e Tensoes)           Zero Cliches de IA)
                   │                             │                             │
                   └─────────────────────────────┼─────────────────────────────┘
                                                 ▼
                                     [Obsidian Writer (Vault)]
                                       - 01_Wiki_Disciplinas/
                                       - 02_Zettelkasten/
                                       - 03_Auditoria_Factual/
                                       - 04_Diario_Tensoes/
```

## Requisitos de Ambiente

- **Linguagem:** Python 3.12+
- **Gerenciador de Pacotes:** Astral `uv`
- **Ambiente:** Windows (com suporte opcional a GPUs NVIDIA com CUDA 12 para transcricao acelerada)
- **Obsidian:** Cofre configurado localmente

## Instalacao

Sincronize as dependencias do projeto com `uv`:

```bash
uv sync
```

O projeto realiza auto-provisao de dependencias nativas quando necessario:
- O binario do FFmpeg e baixado e configurado automaticamente em `%LOCALAPPDATA%\cathedra\bin` se ausente no sistema.
- DLLs CUDA da NVIDIA sao registradas dinamicamente no Windows quando pacotes compativeis estao presentes.

## Configuracao

As variaveis de ambiente podem ser definidas em um arquivo `.env` na raiz do projeto (consultar `src/mba_wiki/config.py`):

Para o backend Gemini REST, configure `GEMINI_API_KEY` no ambiente ou no `.env`; a chave nao deve
ser colocada no repositorio. Caso seja exposta, revogue-a ou rotacione-a no provedor.

```env
OBSIDIAN_VAULT_PATH=C:/Caminho/Para/Seu/Vault_MBA
LLM_PROVIDER=antigravity_cli
LLM_MODEL=gemini-2.5-flash
LLM_MODEL_AUDITOR=gemini-2.5-pro
```

## Comandos da CLI

A aplicacao disponibiliza a interface de comando via `uv run mba-wiki`:

### 1. Inicializar Ementa do Curso

Converte o documento textual ou resumo do programa do curso em `data/raw/ementa_estruturada.json` e inicializa o MOC no cofre:

```bash
uv run mba-wiki init-syllabus caminho/para/programa_do_curso.txt
```

### 2. Transcricao em Lote de Videoaulas

Processa videos em MP4 organizados por pastas de disciplinas, gerando JSONs estruturados em `data/raw/transcripts/`:

```bash
uv run mba-wiki transcribe-batch caminho/para/videos/ --model large-v3
```

- Pula um video apenas quando o checkpoint confere com o hash do arquivo e a configuracao de transcricao.
- Se o video ou a configuracao mudar, reprocessa e guarda o JSON anterior em `.history/<disciplina>/`.
- JSONs antigos ou invalidos ficam como nao verificados; `--force` autoriza reprocessa-los preservando uma copia. Colisoes de destino interrompem o lote, mesmo com `--force`.
- A leitura do video para calcular o SHA-256 tem custo de I/O. O nome do modelo e a versao da biblioteca nao identificam alteracoes nos pesos sob o mesmo nome; evite executar lotes concorrentes sobre os mesmos destinos.
- A migracao automatica de JSONs antigos foi desativada para preservar os arquivos existentes.

### 3. Processar Aula e Gerar Wiki

Executa o pipeline completo para uma aula a partir do slide correspondente:

```bash
uv run mba-wiki build-lesson caminho/para/slide.pdf --discipline lideranca-estrategica --lesson 1
```

Opcoes disponiveis:
- `--transcript` ou `-T`: Caminho explicito do JSON da transcricao da videoaula.
- `--title` ou `-t`: Titulo descritivo da aula (caso nao venha do primeiro slide).
- `--force`: Permite tentar recuperar delimitadores ausentes durante o reprocessamento.

Um caminho explicito deve existir e a disciplina do JSON deve corresponder a aula; se o JSON
contiver `lesson_number`, ele tambem deve corresponder. Transcricoes antigas sem esse campo podem
ser usadas por escolha explicita, que declara a associacao com a aula. Sem `--transcript`, o
programa procura nos diretorios `data/raw/transcripts/<disciplina>/` e `geral/` uma unica
transcricao com `discipline_slug` e `lesson_number` correspondentes. Candidatas ambiguas ou
arquivos sem identificacao junto de uma candidata exigem escolha explicita. Se nao houver candidata,
o comando informa que seguira sem transcricao.

O comando `transcribe-batch` nao infere o numero da aula pelo nome do video; seus JSONs sem
`lesson_number` devem ser informados explicitamente ate que esse campo seja preenchido com um numero
confirmado. Para preencher `discipline_slug` e `lesson_number` em lote a partir da ementa e dos
prefixos numericos sem retranscrever os videos, use `uv run mba-wiki bind-transcripts --dry-run` e
depois execute sem `--dry-run`. O relatorio de auditoria registra o caminho absoluto do JSON, o nome do video original
e se a escolha foi explicita, automatica ou em memoria.

Em paginas de aula existentes, o reprocessamento preserva o frontmatter e as anotacoes fora do
bloco automatico; o frontmatter pode continuar com metadados da criacao. Se faltarem marcadores,
`--force` preserva o texto anterior e acrescenta um novo bloco, que pode exigir revisao manual.
Marcadores duplicados ou invertidos exigem correcao manual.

O processamento de uma aula prepara os arquivos antes de grava-los no cofre e tenta restaurar as
versoes anteriores se uma substituicao falhar. Se uma restauracao nao for segura, o comando informa
onde foram mantidas as copias. A operacao nao garante atomicidade entre arquivos em caso de queda
abrupta do processo ou do computador; evite editar os mesmos arquivos durante a exportacao.

Se a auditoria factual identificar bloqueadores nao resolvidos, a aula nao e publicada.
O relatorio fica em `03_Auditoria_Factual/pendentes/` para revisao; `--force` nao ignora esse bloqueio.
Apos a reescrita, uma segunda chamada ao auditor verifica o texto e os Zettels finais;
qualquer desvio apontado nessa etapa tambem interrompe a publicacao para revisao.
O veredito `verified` indica apoio identificado no material de aula fornecido, nao verificacao
independente. A bibliografia listada nao e consultada automaticamente. O programa confere a
localizacao literal do trecho citado, mas nao garante sua pertinencia ou a correcao da fonte.

### 4. Sincronizar Diario de Tensoes

Reindexa todas as notas de tensoes dialeticas registradas no cofre e atualiza o indice geral:

```bash
uv run mba-wiki sync-tensions
```

## Qualidade e Testes

O projeto segue padroes estritos de engenharia com tipagem completa e testes automatizados:

```bash
# Executar suite completa de testes
uv run pytest -v

# Checar formatacao e lint
uv run ruff check . && uv run ruff format --check .

# Checar tipagem estatica estrita
uv run mypy src/
```

## Documentacao Complementar

- `docs/SPEC.md`: Especificacao tecnica funcional, schemas Pydantic e arquitetura do grafo.
- `docs/PLAN.md`: Backlog de etapas de implementacao e rastreabilidade historica.
- `docs/TRANSCRIPTION_SPEC.md`: Especificacao do motor de audio e transcricao desacoplada.
- `docs/TEMPLATES_OBSIDIAN.md`: Especificacao de templates Markdown e delimitadores de idempotencia no Obsidian.
- `docs/LINTER_RULES.md`: Regras lexicas e sintaticas do linter estilistico Humanizer PT-BR.
- `docs/INTEGRATIONS.md`: Contratos de clientes LLM, transporte e infraestrutura de hardware.
