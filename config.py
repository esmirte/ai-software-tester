"""Configurações centrais do AI Software Tester."""
from __future__ import annotations

import logging
import os
from dataclasses import dataclass, field
from pathlib import Path

BASE_DIR = Path(__file__).resolve().parent


@dataclass(frozen=True)
class Settings:
    timeout_s: int = 60                 # limite de tempo por execução
    memory_mb: int = 512                # limite de memória (Linux/macOS)
    cpu_seconds: int = 60               # limite de CPU (Linux/macOS)
    use_docker: bool = False            # sandbox forte (requer Docker)
    docker_image: str = "ai-tester-sandbox"
    use_ai: bool = False                # usar LLM para explicar/sugerir
    ai_model: str = os.getenv("AI_MODEL", "claude-sonnet-5-5")
    db_path: Path = field(default_factory=lambda: BASE_DIR / "data" / "runs.db")
    logs_dir: Path = field(default_factory=lambda: BASE_DIR / "logs")
    workspace_dir: Path = field(default_factory=lambda: BASE_DIR / "workspace")


def setup_logging(settings: Settings) -> None:
    settings.logs_dir.mkdir(parents=True, exist_ok=True)
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s | %(levelname)s | %(name)s | %(message)s",
        handlers=[
            logging.FileHandler(settings.logs_dir / "executions.log", encoding="utf-8"),
            logging.StreamHandler(),
        ],
    )
