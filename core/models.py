"""Modelos de dados compartilhados entre os módulos."""
from __future__ import annotations

from dataclasses import dataclass, field


@dataclass
class Issue:
    file: str
    line: int
    severity: str          # error | warning | info
    category: str          # bug | security | performance | style | syntax
    rule: str
    message: str
    suggestion: str = ""


@dataclass
class FunctionInfo:
    name: str
    lineno: int
    args: list[str]
    required_args: list[str]
    annotations: dict[str, str]
    returns: str | None
    raises: list[str]
    complexity: int
    length: int
    has_docstring: bool


@dataclass
class FileAnalysis:
    path: str
    lines: int
    syntax_ok: bool
    quality_score: float
    functions: list[FunctionInfo] = field(default_factory=list)
    issues: list[Issue] = field(default_factory=list)


@dataclass
class GeneratedTest:
    filename: str
    code: str
    target: str            # arquivo-alvo (relativo ao projeto)
    n_tests: int = 0


@dataclass
class TestResult:
    __test__ = False       # evita coleta pelo pytest
    name: str
    outcome: str           # passed | failed | skipped | error
    duration: float
    message: str = ""
    target: str = ""
    explanation: str = ""
    suggestion: str = ""


@dataclass
class RunSummary:
    total: int = 0
    passed: int = 0
    failed: int = 0
    skipped: int = 0
    errors: int = 0
    duration: float = 0.0
    timed_out: bool = False
    results: list[TestResult] = field(default_factory=list)
    output: str = ""

    @property
    def pass_rate(self) -> float:
        executed = self.total - self.skipped
        return round(100.0 * self.passed / executed, 2) if executed > 0 else 0.0
