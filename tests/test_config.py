"""Unit tests for the application configuration module."""

from pathlib import Path

import pytest

from cathedra.config import Settings, get_settings


def test_default_settings(monkeypatch: pytest.MonkeyPatch) -> None:
    """Tests default settings values when no environment variables are set.

    Args:
        None.

    Returns:
        None.

    Raises:
        None.
    """
    for name in (
        "OBSIDIAN_VAULT_PATH",
        "SYLLABUS_JSON_PATH",
        "LLM_BACKEND",
        "LLM_PROVIDER",
        "LLM_MODEL_DRAFTER",
        "LLM_MODEL_AUDITOR",
        "GEMINI_API_KEY",
    ):
        monkeypatch.delenv(name, raising=False)
    settings = Settings(_env_file=None)
    assert settings.obsidian_vault_path == Path("vault_mba")
    assert settings.syllabus_json_path is None
    assert settings.llm_provider == "gemini"
    assert settings.llm_model_drafter == "gemini-2.5-pro"
    assert settings.llm_model_auditor == "gemini-2.5-pro"
    assert settings.gemini_api_key is None

    expected_vault = Path("vault_mba")
    assert settings.course_program_path == expected_vault / "00_Programa_Curso"
    assert settings.wiki_path == expected_vault / "01_Wiki_Disciplinas"
    assert settings.zettel_path == expected_vault / "02_Zettelkasten"
    assert settings.audit_path == expected_vault / "03_Auditoria_Factual"
    assert settings.tensions_path == expected_vault / "04_Diario_Tensoes"
    assert (
        settings.resolved_syllabus_json_path
        == expected_vault / "00_Programa_Curso" / "ementa_estruturada.json"
    )


def test_custom_settings(tmp_path: Path) -> None:
    """Tests settings initialization with explicit custom arguments.

    Args:
        tmp_path: Temporary directory fixture provided by pytest.

    Returns:
        None.

    Raises:
        None.
    """
    custom_vault = tmp_path / "custom_vault"
    custom_syllabus = tmp_path / "custom_syllabus.json"

    settings = Settings(
        obsidian_vault_path=custom_vault,
        syllabus_json_path=custom_syllabus,
        llm_provider="openai",
        llm_model_drafter="gpt-4o",
        llm_model_auditor="gpt-4o-mini",
        gemini_api_key="custom-key-123",
    )

    assert settings.obsidian_vault_path == custom_vault
    assert settings.syllabus_json_path == custom_syllabus
    assert settings.resolved_syllabus_json_path == custom_syllabus
    assert settings.llm_provider == "openai"
    assert settings.llm_model_drafter == "gpt-4o"
    assert settings.llm_model_auditor == "gpt-4o-mini"
    assert settings.gemini_api_key is not None
    assert settings.gemini_api_key.get_secret_value() == "custom-key-123"
    assert settings.wiki_path == custom_vault / "01_Wiki_Disciplinas"


def test_settings_from_environment(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """Tests loading settings from environment variables.

    Args:
        tmp_path: Temporary directory fixture provided by pytest.
        monkeypatch: MonkeyPatch fixture provided by pytest.

    Returns:
        None.

    Raises:
        None.
    """
    env_vault = tmp_path / "env_vault"
    env_syllabus = env_vault / "00_Programa_Curso" / "ementa_estruturada.json"

    monkeypatch.setenv("OBSIDIAN_VAULT_PATH", str(env_vault))
    monkeypatch.setenv("SYLLABUS_JSON_PATH", str(env_syllabus))
    monkeypatch.setenv("LLM_PROVIDER", "gemini")
    monkeypatch.setenv("LLM_MODEL_DRAFTER", "gemini-2.5-pro")
    monkeypatch.setenv("LLM_MODEL_AUDITOR", "gemini-2.5-flash")
    monkeypatch.setenv("GEMINI_API_KEY", "test_gemini_api_key_xyz")

    settings = Settings()

    assert settings.obsidian_vault_path == env_vault
    assert settings.syllabus_json_path == env_syllabus
    assert settings.resolved_syllabus_json_path == env_syllabus
    assert settings.llm_provider == "gemini"
    assert settings.llm_model_drafter == "gemini-2.5-pro"
    assert settings.llm_model_auditor == "gemini-2.5-flash"
    assert settings.gemini_api_key is not None
    assert settings.gemini_api_key.get_secret_value() == "test_gemini_api_key_xyz"


def test_ensure_vault_directories(tmp_path: Path) -> None:
    """Tests creation of standard Obsidian vault topology directories.

    Args:
        tmp_path: Temporary directory fixture provided by pytest.

    Returns:
        None.

    Raises:
        None.
    """
    vault_dir = tmp_path / "obsidian_vault"
    settings = Settings(obsidian_vault_path=vault_dir)

    assert not vault_dir.exists()
    settings.ensure_vault_directories()

    assert settings.obsidian_vault_path.is_dir()
    assert settings.course_program_path.is_dir()
    assert settings.wiki_path.is_dir()
    assert settings.zettel_path.is_dir()
    assert settings.audit_path.is_dir()
    assert settings.tensions_path.is_dir()


def test_get_settings_cached() -> None:
    """Tests get_settings function returns a cached singleton instance.

    Args:
        None.

    Returns:
        None.

    Raises:
        None.
    """
    get_settings.cache_clear()
    s1 = get_settings()
    s2 = get_settings()
    assert s1 is s2
    get_settings.cache_clear()
