"""Unit tests for the deterministic prose linter (validators.py).

Tests enforcement of typographic, punctuation, structural, and lexical blacklist
rules specified in docs/LINTER_RULES.md.
"""

from cathedra.agents.validators import (
    LinterViolation,
    ValidationResult,
    mask_ignored_elements,
    validate_markdown_prose,
)


def test_clean_academic_prose_passes() -> None:
    """Tests that clean, professional academic prose passes validation with zero violations.

    Args:
        None.

    Returns:
        None.

    Raises:
        None.
    """
    clean_text = (
        "O método do Valor Presente Líquido considera o valor do dinheiro no tempo. "
        "Ele desconta fluxos de caixa futuros utilizando o custo de oportunidade do capital. "
        "Dessa forma, projetos com resultado positivo geram acréscimo patrimonial.\n\n"
        "Em contrapartida, a Taxa Interna de Retorno apresenta limitações teóricas. "
        "A suposição de reinvestimento dos fluxos à própria taxa interna distorce a análise. "
        "Por essa razão, gestores financeiros priorizam o critério do VPL na tomada de decisão."
    )
    result = validate_markdown_prose(clean_text)
    assert result.is_valid is True
    assert len(result.violations) == 0


def test_bad_ai_prose_fixture_fails(bad_ai_prose_text: str) -> None:
    """Tests that the bad_ai_prose.md fixture triggers violations across all rule families.

    Args:
        bad_ai_prose_text: Text loaded from tests/fixtures/bad_ai_prose.md.

    Returns:
        None.

    Raises:
        None.
    """
    result = validate_markdown_prose(bad_ai_prose_text)
    assert result.is_valid is False
    assert len(result.violations) > 0

    rule_ids = {v.rule_id for v in result.violations}

    # Verify mechanical rules R1 to R4 are triggered
    assert "R1_DASH" in rule_ids
    assert "R2_SYMBOL" in rule_ids
    assert "R3_PARAGRAPH_LENGTH" in rule_ids
    assert "R4_AI_BULLET" in rule_ids

    # Verify lexical blacklist groups L1 to L7 are triggered
    assert "L1_AI_OPENER" in rule_ids
    assert "L2_EMPTY_APHORISM" in rule_ids
    assert "L3_METAPHOR" in rule_ids
    assert "L4_HISTRIONIC_ADJECTIVE" in rule_ids
    assert "L5_STIFF_CONNECTIVE" in rule_ids
    assert "L6_AI_CLOSING" in rule_ids
    assert "L7_ASSISTANT_RESIDUE" in rule_ids


def test_r1_prohibited_dashes() -> None:
    """Tests that em-dashes and en-dashes are rejected while standard hyphens are allowed.

    Args:
        None.

    Returns:
        None.

    Raises:
        None.
    """
    em_dash_text = "O investimento em capital de giro — embora necessário — reduz a liquidez."
    result_em = validate_markdown_prose(em_dash_text)
    assert result_em.is_valid is False
    assert any(v.rule_id == "R1_DASH" for v in result_em.violations)

    en_dash_text = "O investimento em capital de giro – embora necessário – reduz a liquidez."
    result_en = validate_markdown_prose(en_dash_text)
    assert result_en.is_valid is False
    assert any(v.rule_id == "R1_DASH" for v in result_en.violations)

    # Standard hyphen for compound words should be accepted
    hyphen_text = "O curso de pós-graduação analisa a relação custo-benefício de novos projetos."
    result_hyphen = validate_markdown_prose(hyphen_text)
    assert not any(v.rule_id == "R1_DASH" for v in result_hyphen.violations)


def test_r2_decorative_symbols_and_emojis() -> None:
    """Tests that decorative arrows and Unicode emojis are flagged as violations.

    Args:
        None.

    Returns:
        None.

    Raises:
        None.
    """
    arrow_text = "A expansão de receitas → aumento de margens → maiores lucros."
    result_arrow = validate_markdown_prose(arrow_text)
    assert any(v.rule_id == "R2_SYMBOL" for v in result_arrow.violations)

    emoji_text = "O projeto foi aprovado pelo comitê executivo com sucesso 🚀."
    result_emoji = validate_markdown_prose(emoji_text)
    assert any(v.rule_id == "R2_SYMBOL" for v in result_emoji.violations)


def test_r3_paragraph_sentence_limit() -> None:
    """Tests that paragraphs exceeding 4 sentences trigger R3_PARAGRAPH_LENGTH.

    Args:
        None.

    Returns:
        None.

    Raises:
        None.
    """
    # 5 sentences paragraph should fail
    five_sentences = (
        "Primeira frase do parágrafo explicativo. "
        "Segunda frase trazendo contexto adicional. "
        "Terceira frase aprofundando o modelo numérico. "
        "Quarta frase estabelecendo a correlação observada. "
        "Quinta frase excedendo o limite permitido pelo linter."
    )
    result_fail = validate_markdown_prose(five_sentences)
    assert any(v.rule_id == "R3_PARAGRAPH_LENGTH" for v in result_fail.violations)

    # 4 sentences paragraph should pass
    four_sentences = (
        "Primeira frase do parágrafo explicativo. "
        "Segunda frase trazendo contexto adicional. "
        "Terceira frase aprofundando o modelo numérico. "
        "Quarta frase estabelecendo a correlação observada."
    )
    result_pass = validate_markdown_prose(four_sentences)
    assert not any(v.rule_id == "R3_PARAGRAPH_LENGTH" for v in result_pass.violations)


def test_r3_ignores_abbreviations_and_decimals() -> None:
    """Tests that common abbreviations and decimals do not cause false sentence counts.

    Args:
        None.

    Returns:
        None.

    Raises:
        None.
    """
    abbreviation_text = (
        "O Prof. Roberto Albuquerque apresentou o modelo econômico às 14h. "
        "O Dr. Silva e sua equipe, i.e., os analistas seniores, avaliaram a taxa de 12.5%. "
        "Segundo Brealey et al., o retorno esperado deve superar a taxa Selic. "
        "A análise comparativa de VPL vs. TIR comprovou a viabilidade do investimento."
    )
    result = validate_markdown_prose(abbreviation_text)
    assert not any(v.rule_id == "R3_PARAGRAPH_LENGTH" for v in result.violations)


def test_r4_ai_mechanical_bullet_patterns() -> None:
    """Tests detection of AI-style mechanical bullet points with bold prefixes.

    Args:
        None.

    Returns:
        None.

    Raises:
        None.
    """
    bullet_prose = (
        "Os principais indicadores de retorno são:\n"
        "- **VPL:** mensura o ganho em termos absolutos de valor.\n"
        "- **TIR:** reflete a rentabilidade percentual intrínseca do projeto."
    )
    result = validate_markdown_prose(bullet_prose)
    assert any(v.rule_id == "R4_AI_BULLET" for v in result.violations)


def test_lexical_blacklist_individual_groups() -> None:
    """Tests that each lexical blacklist category L1-L7 triggers its specific rule ID.

    Args:
        None.

    Returns:
        None.

    Raises:
        None.
    """
    # L1: AI opener
    res_l1 = validate_markdown_prose("No cenário atual, a liquidez é essencial.")
    assert any(v.rule_id == "L1_AI_OPENER" for v in res_l1.violations)

    # L2: Empty aphorism
    res_l2 = validate_markdown_prose("No seu cerne, o problema decorre do endividamento.")
    assert any(v.rule_id == "L2_EMPTY_APHORISM" for v in res_l2.violations)

    # L3: Metaphor / Figured verb
    res_l3 = validate_markdown_prose("Precisamos alavancar os recursos para obter lucro.")
    assert any(v.rule_id == "L3_METAPHOR" for v in res_l3.violations)

    # L4: Histrionic adjective
    res_l4 = validate_markdown_prose("Este resultado é crucial para a sobrevivência da firma.")
    assert any(v.rule_id == "L4_HISTRIONIC_ADJECTIVE" for v in res_l4.violations)

    # L5: Stiff connective
    res_l5 = validate_markdown_prose("Ademais, os custos operacionais continuam elevados.")
    assert any(v.rule_id == "L5_STIFF_CONNECTIVE" for v in res_l5.violations)

    # L6: AI closing
    res_l6 = validate_markdown_prose("Em suma, a tomada de decisão deve ser fundamentada.")
    assert any(v.rule_id == "L6_AI_CLOSING" for v in res_l6.violations)

    # L7: Assistant residue
    res_l7 = validate_markdown_prose("Como uma IA, não posso fornecer recomendação de compra.")
    assert any(v.rule_id == "L7_ASSISTANT_RESIDUE" for v in res_l7.violations)


def test_masking_code_blocks_and_latex_equations() -> None:
    """Tests that code blocks, inline code, LaTeX math, and HTML comments are masked.

    Args:
        None.

    Returns:
        None.

    Raises:
        None.
    """
    text_with_technical_artifacts = (
        "Considere a fórmula a seguir para cálculo do indicador:\n\n"
        "$$\n"
        "\\text{VPL} = \\sum_{t=1}^n \\frac{FC_t}{(1 + r)^t} - I_0\n"
        "$$\n\n"
        "Onde $r$ é a taxa de desconto e `delta_t` representa o período. "
        "Consulte o script abaixo:\n\n"
        "```python\n"
        "# Comentário contendo — travessão e palavra crucial ou ademais\n"
        "def compute_npv(rate: float) -> float: ...\n"
        "```\n\n"
        "<!-- Comentário HTML com seta → e emoji 🚀 -->\n"
        "A aplicação prática demonstrou resultados consistentes."
    )
    result = validate_markdown_prose(text_with_technical_artifacts)
    assert result.is_valid is True
    assert len(result.violations) == 0


def test_mask_ignored_elements_function() -> None:
    """Tests that mask_ignored_elements preserves line count while blanking syntax.

    Args:
        None.

    Returns:
        None.

    Raises:
        None.
    """
    raw = (
        "Linha 1\n"
        "```python\n"
        "bloco de codigo\n"
        "```\n"
        "Linha 5 com `codigo inline` e $$display math$$\n"
        "<!-- Comentario -->\n"
        "Linha 7"
    )
    masked = mask_ignored_elements(raw)
    assert raw.count("\n") == masked.count("\n")
    assert "bloco de codigo" not in masked
    assert "codigo inline" not in masked
    assert "display math" not in masked
    assert "Comentario" not in masked
    assert "Linha 1" in masked
    assert "Linha 7" in masked


def test_validation_result_and_violation_dataclasses() -> None:
    """Tests instantiation and attributes of ValidationResult and LinterViolation.

    Args:
        None.

    Returns:
        None.

    Raises:
        None.
    """
    violation = LinterViolation(
        rule_id="R1_DASH",
        message="Travessão proibido",
        line_number=10,
        matched_text="—",
    )
    assert violation.rule_id == "R1_DASH"
    assert violation.message == "Travessão proibido"
    assert violation.line_number == 10
    assert violation.matched_text == "—"

    result = ValidationResult(is_valid=False, violations=[violation])
    assert result.is_valid is False
    assert len(result.violations) == 1


def test_academic_citation_abbreviations_do_not_split_sentences() -> None:
    """Tests that academic page and volume abbreviations do not trigger sentence boundaries.

    Args:
        None.

    Returns:
        None.

    Raises:
        None.
    """
    citation_text = (
        "Segundo Damodaran (2012, p. 45), o fluxo de caixa reflete a geração real de valor. "
        "A análise prossegue no cap. 3 da mesma obra com exemplos empíricos de valuation. "
        "Conforme demonstrado por Brealey e Myers (vol. 2, pp. 110-112), a dívida reduz impostos. "
        "Dessa forma, o gestor financeiro calibra o endividamento ótimo com cautela."
    )
    result = validate_markdown_prose(citation_text)
    assert not any(v.rule_id == "R3_PARAGRAPH_LENGTH" for v in result.violations)


def test_markdown_tables_do_not_trigger_r3_paragraph_limit() -> None:
    """Tests that GFM markdown tables with multiple lines do not trigger R3 paragraph length.

    Args:
        None.

    Returns:
        None.

    Raises:
        None.
    """
    table_prose = (
        "| Indicador | Metodologia | Aplicação Principal |\n"
        "| --- | --- | --- |\n"
        "| VPL | Desconto de fluxos futuros. | Projetos de capital. |\n"
        "| TIR | Taxa que zera o VPL. | Comparação percentual. |\n"
        "| Payback | Tempo de recuperação. | Avaliação de liquidez. |\n"
        "| WACC | Custo médio de capital. | Taxa de desconto mínima. |\n"
        "| CAPM | Retorno versus risco beta. | Custo de capital próprio. |"
    )
    result = validate_markdown_prose(table_prose)
    assert not any(v.rule_id == "R3_PARAGRAPH_LENGTH" for v in result.violations)


def test_ai_bullet_pattern_with_colon_outside_bold() -> None:
    """Tests detection of AI-style mechanical bullet points when colon is outside bold.

    Args:
        None.

    Returns:
        None.

    Raises:
        None.
    """
    bullet_prose = (
        "Os principais conceitos da aula são:\n"
        "- **Valor Presente Líquido**: mensura a riqueza gerada pelo investimento.\n"
        "- **Taxa Interna de Retorno**: taxa que iguala o VPL a zero."
    )
    result = validate_markdown_prose(bullet_prose)
    assert any(v.rule_id == "R4_AI_BULLET" for v in result.violations)


def test_sentence_split_handles_closing_quotes_and_parentheses() -> None:
    """Tests that sentence counting correctly handles sentences ending with quotes or parentheses.

    Args:
        None.

    Returns:
        None.

    Raises:
        None.
    """
    from cathedra.agents.validators import count_sentences

    text_with_quotes = (
        'O autor afirmou: "O VPL é a regra de ouro." '
        'Em seguida, destacou: "A TIR possui limitações." '
        "Por fim, concluiu a análise teórica."
    )
    assert count_sentences(text_with_quotes) == 3


def test_r5_literal_newline_rejects_escaped_prose_and_ignores_latex_and_code() -> None:
    """Tests that R5_LITERAL_NEWLINE flags literal \\n in prose but preserves LaTeX and code.

    Args:
        None.

    Returns:
        None.

    Raises:
        None.
    """
    corrupted = "Primeiro parágrafo.\\n\\nSegundo parágrafo."
    bad_result = validate_markdown_prose(corrupted)
    assert bad_result.is_valid is False
    assert any(v.rule_id == "R5_LITERAL_NEWLINE" for v in bad_result.violations)

    valid_technical = (
        "Quando $\\nu \\neq 0$, o parâmetro controla os graus de liberdade.\n\n"
        "No código inline `sep = '\\n'` ou no bloco abaixo:\n\n"
        "```python\n"
        "print('linha1\\nlinha2')\n"
        "```"
    )
    good_result = validate_markdown_prose(valid_technical)
    assert not any(v.rule_id == "R5_LITERAL_NEWLINE" for v in good_result.violations)


def test_normalized_zettel_exposes_hidden_r4_ai_bullet_violations() -> None:
    """Tests that normalizing double-escaped zettels allows R4_AI_BULLET to catch AI lists.

    Args:
        None.

    Returns:
        None.

    Raises:
        None.
    """
    from cathedra.schemas import AtomicZettel

    zettel = AtomicZettel(
        slug="normalizacao",
        title="Normalização",
        domain_tags=["gis"],
        content_markdown=(
            "Normalização evita distorções:\\n"
            "- **Por habitante:** para taxas populacionais.\\n"
            "- **Por área:** para densidade territorial."
        ),
        related_links=[],
    )
    result = validate_markdown_prose(zettel.content_markdown)
    assert result.is_valid is False
    assert any(v.rule_id == "R4_AI_BULLET" for v in result.violations)


def test_quantitative_mais_do_que_allowed_while_rhetorical_cliche_blocked() -> None:
    """Tests that quantitative 'mais do que' passes while empty AI aphorism fails L2.

    Args:
        None.

    Returns:
        None.

    Raises:
        None.
    """
    quant_prose = (
        "A amostra possui mais do que 30 observações válidas para aplicar o teorema central. "
        "O modelo explicou mais do que 80% da variância dos preços observados."
    )
    quant_result = validate_markdown_prose(quant_prose)
    assert quant_result.is_valid is True

    cliche_prose = "Mais do que uma fórmula, trata-se de uma filosofia de gestão."
    cliche_result = validate_markdown_prose(cliche_prose)
    assert any(v.rule_id == "L2_EMPTY_APHORISM" for v in cliche_result.violations)


def test_plain_lists_and_author_initials_do_not_trigger_r3_paragraph_length() -> None:
    """Tests that plain markdown lists and author initials do not cause false R3 violations.

    Args:
        None.

    Returns:
        None.

    Raises:
        None.
    """
    plain_list = (
        "- Item um da amostra.\n"
        "- Item dois da amostra.\n"
        "- Item três da amostra.\n"
        "- Item quatro da amostra.\n"
        "- Item cinco da amostra."
    )
    list_result = validate_markdown_prose(plain_list)
    assert not any(v.rule_id == "R3_PARAGRAPH_LENGTH" for v in list_result.violations)

    initials_prose = (
        "A Primeira Lei da Geografia de W. Tobler descreve dependência espacial (etc.). "
        "Em seguida, L. Anselin formalizou os indicadores locais (obs. de aula). "
        "M. Porter discutiu posicionamento competitivo em mercados industriais. "
        "Por fim, R. Brealey analisou decisões de investimento corporativo."
    )
    initials_result = validate_markdown_prose(initials_prose)
    assert not any(v.rule_id == "R3_PARAGRAPH_LENGTH" for v in initials_result.violations)
