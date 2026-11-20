"""Configuration management module for Cathedra.

Loads environment variables, vault paths, and API keys using pydantic-settings.
"""

from functools import lru_cache
from pathlib import Path

from pydantic import Field, SecretStr
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    """Application configuration settings for the Cathedra.

    Attributes:
        obsidian_vault_path: Root filesystem path to the Obsidian vault.
        syllabus_json_path: Explicit filesystem path to the structured syllabus JSON file.
        llm_provider: Name of the active LLM provider.
        llm_model_drafter: Model identifier for drafting wiki lessons and zettels.
        llm_model_auditor: Model identifier for factual auditing.
        gemini_api_key: Secret API key for Google Gemini access.
    """

    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
    )

    obsidian_vault_path: Path = Field(
        default=Path("vault_mba"),
        description="Root filesystem path to the Obsidian vault.",
    )
    syllabus_json_path: Path | None = Field(
        default=None,
        description="Explicit filesystem path to the structured syllabus JSON file.",
    )
    llm_backend: str = Field(
        default="gemini",
        description="LLM execution backend ('gemini' for REST API or 'agy' for CLI).",
    )
    llm_provider: str = Field(
        default="gemini",
        description="Name of the active LLM provider.",
    )
    llm_model_drafter: str = Field(
        default="gemini-2.5-pro",
        description="Model identifier for drafting wiki lessons and zettels.",
    )
    llm_model_auditor: str = Field(
        default="gemini-2.5-pro",
        description="Model identifier for factual auditing.",
    )
    gemini_api_key: SecretStr | None = Field(
        default=None,
        description="Secret API key for Google Gemini access.",
    )

    @property
    def course_program_path(self) -> Path:
        """Returns the directory path for course syllabus and dashboard files.

        Args:
            None.

        Returns:
            Path: Filesystem path to the 00_Programa_Curso directory.

        Raises:
            None.
        """
        return self.obsidian_vault_path / "00_Programa_Curso"

    @property
    def wiki_path(self) -> Path:
        """Returns the directory path for wiki discipline folders.

        Args:
            None.

        Returns:
            Path: Filesystem path to the 01_Wiki_Disciplinas directory.

        Raises:
            None.
        """
        return self.obsidian_vault_path / "01_Wiki_Disciplinas"

    @property
    def zettel_path(self) -> Path:
        """Returns the directory path for atomic Zettelkasten notes.

        Args:
            None.

        Returns:
            Path: Filesystem path to the 02_Zettelkasten directory.

        Raises:
            None.
        """
        return self.obsidian_vault_path / "02_Zettelkasten"

    @property
    def audit_path(self) -> Path:
        """Returns the directory path for factual audit logs.

        Args:
            None.

        Returns:
            Path: Filesystem path to the 03_Auditoria_Factual directory.

        Raises:
            None.
        """
        return self.obsidian_vault_path / "03_Auditoria_Factual"

    @property
    def tensions_path(self) -> Path:
        """Returns the directory path for dialectical tension notes.

        Args:
            None.

        Returns:
            Path: Filesystem path to the 04_Diario_Tensoes directory.

        Raises:
            None.
        """
        return self.obsidian_vault_path / "04_Diario_Tensoes"

    @property
    def resolved_syllabus_json_path(self) -> Path:
        """Resolves the syllabus JSON path, falling back to default vault topology.

        Args:
            None.

        Returns:
            Path: Resolved filesystem path to ementa_estruturada.json.

        Raises:
            None.
        """
        if self.syllabus_json_path is not None:
            return self.syllabus_json_path
        return self.course_program_path / "ementa_estruturada.json"

    def ensure_vault_directories(self) -> None:
        """Creates the full standard directory topology in the Obsidian vault if missing.

        Args:
            None.

        Returns:
            None.

        Raises:
            OSError: If directory creation fails due to filesystem permissions.
        """
        self.obsidian_vault_path.mkdir(parents=True, exist_ok=True)
        self.course_program_path.mkdir(parents=True, exist_ok=True)
        self.wiki_path.mkdir(parents=True, exist_ok=True)
        self.zettel_path.mkdir(parents=True, exist_ok=True)
        self.audit_path.mkdir(parents=True, exist_ok=True)
        self.tensions_path.mkdir(parents=True, exist_ok=True)


@lru_cache
def get_settings() -> Settings:
    """Returns a cached singleton instance of the application Settings.

    Args:
        None.

    Returns:
        Settings: The loaded application settings instance.

    Raises:
        pydantic.ValidationError: If environment variables contain invalid configuration.
    """
    return Settings()


__all__ = ["Settings", "get_settings"]
