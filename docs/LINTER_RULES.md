# Regras Deterministicas do Linter Estilistico (Humanizer PT-BR)

Este documento especifica os contratos e algoritmos que devem ser implementados em `src/cathedra/agents/validators.py` para inspecionar e validar textos em prosa gerados pelo pipeline antes da aprovacao e persistencia no cofre Obsidian.

---

## 1. Escopo de Aplicacao
- **Alvo:** O linter atua estritamente sobre blocos de prosa (`body_markdown` em `WikiLessonOutput` e `content_markdown` em `AtomicZettel`).
- **Isolamento:** O linter **nao** deve ser executado sobre o arquivo final completo pos-template, evitando falsos positivos nas seções de metadados YAML, tabelas geradas ou listas estruturais de navegacao (`## Conexoes Diretas`, `## Referencias no Curso`, etc.).
- **Pre-processamento para analise:**
  1. Blocos de codigo cercados por crases triplas (```...```) e codigo inline (`...`) devem ser mascarados/ignorados.
  2. Formulas matematicas LaTeX em display (`$$...$$`) e inline (`$...$`) devem ser ignoradas.
  3. Comentarios HTML (`<!-- ... -->`) devem ser ignorados.

---

## 2. Regras Mecanicas e de Pontuacao

### Regra R1: Proibicao Absoluta de Travessoes Explicativos
- **Caracteres proibidos:**
  - Travessao: `—` (`\u2014`)
  - Meia-risca: `–` (`\u2013`)
- **Excecoes:** O hifen comum `-` (`\u002D`) e permitido exclusivamente para hifenizacao de palavras compostas (ex: `pos-graduacao`) ou sintaxe de listas fora do corpo de prosa.
- **Regex de captura:**
  ```python
  RE_PROHIBITED_DASHES = r"[—–]"
  ```
- **Severidade:** Erro bloqueante (rejeicao imediata).

### Regra R2: Proibicao de Emojis e Simbolos Decorativos
- **Simbolos proibidos:** Emojis Unicode e setas decorativas comuns em saidas de IA.
- **Regexes de captura:**
  ```python
  # Setas estilizadas
  RE_DECORATIVE_ARROWS = r"[→⇒←⇐↔↕↗↘↖↙]"

  # Faixas comuns de emojis Unicode
  RE_EMOJIS = r"[\U0001F300-\U0001FAFF]|[\U00002600-\U000027BF]"
  ```
- **Severidade:** Erro bloqueante.

### Regra R3: Teto de 4 Frases por Paragrafo
- **Regra:** Nenhum paragrafo de texto corrido pode conter mais de 4 frases.
- **Definicao de paragrafo:** Blocos de texto separados por duas ou mais quebras de linha (`\n\n+`), excluindo titulos (`#`, `##`, etc.) e citacoes em bloco (`>`).
- **Definicao de sentenca:** Delimitada por pontuacao final (`.`, `!`, `?`) seguida de espaco em branco ou fim de linha, com desconsideracao de abreviacoes comuns (ex: `ex.`, `i.e.`, `e.g.`, `Dr.`, `Prof.`, `et al.`, `vs.`) e numeros decimais.
- **Severidade:** Erro bloqueante.

### Regra R4: Proibicao de Listas Mecanicas no Corpo da Prosa
- **Regra:** O corpo explicativo (`body_markdown`) deve ser redigido em prosa contínua articulada. Listas com hífens ou números que adotam o padrão clichê de IA (`- **Conceito:** explicação`) são proibidas.
- **Regex de captura:**
  ```python
  RE_AI_BULLET_PATTERN = r"^\s*[-*]\s+\*\*[^*]+:\*\*\s+"
  ```
- **Severidade:** Erro bloqueante.

---

## 3. Lista Negra Lexical (Banimento Estrito)

O validador deve checar, de forma insensivel a maiusculas/minusculas (*case-insensitive*) e respeitando limites de palavras (`\b`), os termos e expressoes listados abaixo:

### Grupo L1: Aberturas de IA
- `"no cenário atual"`
- `"no mundo dinâmico de hoje"`
- `"na era da informação"`
- `"não é segredo que"`
- `"vamos mergulhar"`
- `"vamos examinar"`

### Grupo L2: Aforismos Ocos e Contrastes Vazios
- `"no seu cerne"`
- `"a verdadeira questão é"`
- `"o que realmente importa é"`
- `"na essência"`
- `"não é apenas sobre"`
- `"mais do que"`

### Grupo L3: Metaforas Gastas e Verbos Figurados
- `"mergulho profundo"`
- `"desbloquear o potencial"`
- `"navegar pelo cenário"`
- `"faca de dois gumes"`
- `"tapeçaria"`
- `"mosaico"`
- `"sinfonia"`
- `"virada de chave"`
- `"game changer"`
- `"alavancar"`
- `"fomentar"`
- `"potencializar"`

### Grupo L4: Adjetivos Histrionicos
- `"crucial"`
- `"fundamental"`
- `"pivotal"`
- `"revolucionário"`
- `"fascinante"`
- `"incrível"`
- `"imprescindível"`
- `"disruptivo"`

### Grupo L5: Conectivos Engessados
- `"outrossim"`
- `"ademais"`
- `"destarte"`
- `"por conseguinte"`
- `"vale ressaltar que"`
- `"é importante notar que"`
- `"cabe destacar"`

### Grupo L6: Fechamentos Otimistas de IA
- `"em suma"`
- `"em resumo"`
- `"concluindo"`
- `"o futuro parece promissor"`
- `"tempos empolgantes estão por vir"`

### Grupo L7: Residuos de Assistente / Conversacionais
- `"espero que ajude"`
- `"com certeza"`
- `"excelente pergunta"`
- `"como uma ia"`
- `"como modelo de linguagem"`

---

## 4. Retorno Estruturado do Validador

A funcao de validacao em `validators.py` deve retornar um objeto estrito com os resultados encontrados:

```python
from dataclasses import dataclass, field


@dataclass(frozen=True)
class LinterViolation:
    rule_id: str  # Ex: "R1_DASH", "R3_PARAGRAPH_LENGTH", "L3_METAPHOR"
    message: str  # Explicacao amigavel para realimentar o prompt da LLM
    line_number: int | None = None
    matched_text: str | None = None


@dataclass
class ValidationResult:
    is_valid: bool
    violations: list[LinterViolation] = field(default_factory=list)
```

---

## 5. Politica de Retentativa no Humanizer Node
1. O texto reescrito pela LLM e submetido a `validate_markdown_prose(text)`.
2. Se `is_valid` for `True`, o estado e aprovado para o proximo estagio (`persistence_node`).
3. Se `is_valid` for `False`, os erros em `violations` sao formatados como instrucao de correcao pontual e enviados de volta a LLM.
4. **Limite:** Sao permitidas ate **3 tentativas** de autocorrecao.
5. **Fallback:** Caso o texto ainda apresente violacoes apos a 3ª tentativa, o pipeline registra um alerta com as violacoes restantes, marca `humanizer_passed: False` no estado e lanca `ValidationError` interrompendo o build para evitar poluicao de dados no cofre.
