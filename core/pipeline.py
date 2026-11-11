"""Orquestração: analisar -> gerar testes -> executar em sandbox -> explicar -> persistir."""
from __future__ import annotations

import logging
import shutil
import tempfile
from dataclasses import asdict
from pathlib import Path
from typing import Any

from ai_engine.engine import AIEngine
from analyzer.static_analyzer import StaticAnalyzer
from config import Settings
from core.models import FileAnalysis, GeneratedTest, RunSummary
from database.db import RunRepository
from reports.report_builder import ReportBuilder
from test_generator.generator import TestGenerator
from test_runner.sandbox import SandboxRunner

log = logging.getLogger("pipeline")


class QAPipeline:
    """Coordena os módulos (injeção de dependências facilita testes e extensão)."""

    def __init__(self, settings: Settings, analyzer: StaticAnalyzer | None = None,
                 generator: TestGenerator | None = None, runner: SandboxRunner | None = None,
                 ai: AIEngine | None = None, repo: RunRepository | None = None,
                 reporter: ReportBuilder | None = None):
        self.settings = settings
        self.analyzer = analyzer or StaticAnalyzer()
        self.generator = generator or TestGenerator()
        self.runner = runner or SandboxRunner(settings)
        self.ai = ai or AIEngine(settings.use_ai, settings.ai_model)
        self.repo = repo or RunRepository(settings.db_path)
        self.reporter = reporter or ReportBuilder()

    # -------- etapas individuais (usadas pela interface) --------
    def analyze(self, project: Path) -> list[FileAnalysis]:
        return self.analyzer.analyze_project(project)

    def generate(self, project: Path, analyses: list[FileAnalysis]) -> list[GeneratedTest]:
        tests = self.generator.generate_for_project(analyses)
        if self.ai.available:
            for t in tests:
                extra = self.ai.suggest_tests((project / t.target).read_text(encoding="utf-8", errors="replace"))
                if extra and self.generator.is_valid_python(t.code + "\n\n" + extra):
                    t.code += "\n\n# --- testes sugeridos pela IA ---\n" + extra + "\n"
        return tests

    # -------- execução completa --------
    def run_project(self, project: Path, label: str = "") -> dict[str, Any]:
        project = Path(project).resolve()
        analyses = self.analyze(project)
        tests = self.generate(project, analyses)
        summary = self.runner.run(project, tests) if tests else RunSummary(output="Nenhum teste gerado.")
        self._explain_failures(project, summary)
        run = self._build_run(project, label, analyses, tests, summary)
        run["id"] = self.repo.save(run)
        return run

    def run_code(self, code: str, filename: str = "snippet.py", label: str = "") -> dict[str, Any]:
        self.settings.workspace_dir.mkdir(parents=True, exist_ok=True)
        tmp = Path(tempfile.mkdtemp(prefix="snippet_", dir=self.settings.workspace_dir))
        try:
            (tmp / Path(filename).name).write_text(code, encoding="utf-8")
            return self.run_project(tmp, label or filename)
        finally:
            shutil.rmtree(tmp, ignore_errors=True)

    # -------- comparação de versões --------
    def compare(self, run_a: int, run_b: int) -> dict[str, Any]:
        a, b = self.repo.get(run_a), self.repo.get(run_b)
        if not a or not b:
            raise KeyError("Execução não encontrada.")

        def failing(r: dict) -> set[str]:
            return {f"{x['target']}::{x['name']}" for x in r["summary"]["results"] if x["outcome"] in ("failed", "error")}
        fa, fb = failing(a), failing(b)
        return {"pass_rate_delta": round(b["summary"]["pass_rate"] - a["summary"]["pass_rate"], 2),
                "quality_delta": round(b.get("quality_score", 0) - a.get("quality_score", 0), 1),
                "fixed": sorted(fa - fb), "new_failures": sorted(fb - fa), "still_failing": sorted(fa & fb)}

    # -------- internos --------
    def _explain_failures(self, project: Path, summary: RunSummary) -> None:
        for r in summary.results:
            if r.outcome in ("failed", "error"):
                src = ""
                f = project / r.target
                if f.is_file():
                    src = f.read_text(encoding="utf-8", errors="replace")
                r.explanation, r.suggestion = self.ai.explain_failure(r.name, r.message, src)

    @staticmethod
    def _recommendations(analyses: list[FileAnalysis], summary: RunSummary) -> list[str]:
        recs = []
        if summary.timed_out:
            recs.append("A execução estourou o tempo limite: procure laços infinitos ou operações lentas.")
        if summary.failed + summary.errors:
            recs.append("Corrija primeiro as falhas de testes de casos extremos: costumam indicar bugs reais.")
        rules = {i.rule for a in analyses for i in a.issues}
        if rules & {"EVAL_EXEC", "SHELL_TRUE", "OS_COMMAND", "HARDCODED_SECRET", "PICKLE"}:
            recs.append("Há vulnerabilidades de segurança: trate-as antes de publicar.")
        if "NO_DOCSTRING" in rules:
            recs.append("Adicione docstrings às funções públicas.")
        if "HIGH_COMPLEXITY" in rules or "LONG_FUNCTION" in rules:
            recs.append("Refatore funções longas/complexas para facilitar testes e manutenção.")
        if summary.total == 0:
            recs.append("Nenhum teste pôde ser gerado: adicione funções de nível de módulo ou revise erros de sintaxe.")
        return recs or ["Código em bom estado. Considere adicionar testes de integração e de API."]

    def _build_run(self, project: Path, label: str, analyses: list[FileAnalysis],
                   tests: list[GeneratedTest], summary: RunSummary) -> dict[str, Any]:
        issues = [asdict(i) for a in analyses for i in a.issues]
        affected = sorted({r.target for r in summary.results if r.outcome in ("failed", "error")}
                          | {i["file"] for i in issues if i["severity"] == "error"})
        scores = [a.quality_score for a in analyses]
        return {
            "created_at": self.repo.now(), "label": label or project.name, "project": str(project),
            "quality_score": round(sum(scores) / len(scores), 1) if scores else 0.0,
            "summary": {**{k: getattr(summary, k) for k in
                           ("total", "passed", "failed", "skipped", "errors", "duration", "timed_out", "output")},
                        "pass_rate": summary.pass_rate, "results": [asdict(r) for r in summary.results]},
            "issues": issues, "files_affected": affected,
            "generated_tests": [{"filename": t.filename, "target": t.target, "n_tests": t.n_tests, "code": t.code}
                                for t in tests],
            "recommendations": self._recommendations(analyses, summary),
            "ai_used": self.ai.available,
        }
