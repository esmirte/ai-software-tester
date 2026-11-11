"""Testes do próprio sistema."""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from analyzer.static_analyzer import StaticAnalyzer  # noqa: E402
from config import Settings  # noqa: E402
from core.pipeline import QAPipeline  # noqa: E402

BUGGY = '''
password = "123456"

def dividir(a: int, b: int) -> float:
    """Divide a por b."""
    return a / b

def soma(a: int, b: int) -> int:
    """Soma."""
    return a + b

def acessa(lista: list, i: int):
    """Acessa."""
    return lista[i]
'''


def test_analyzer_detects_issues():
    fa = StaticAnalyzer().analyze_source("def f(x=[]):\n    eval('1')\n", "x.py")
    rules = {i.rule for i in fa.issues}
    assert {"MUTABLE_DEFAULT", "EVAL_EXEC"} <= rules


def test_analyzer_syntax_error():
    fa = StaticAnalyzer().analyze_source("def f(:\n", "bad.py")
    assert not fa.syntax_ok and fa.issues[0].rule == "SYNTAX"


def test_pipeline_finds_real_bug(tmp_path):
    s = Settings(db_path=tmp_path / "db.sqlite", logs_dir=tmp_path, workspace_dir=tmp_path / "ws", timeout_s=60)
    run = QAPipeline(s).run_code(BUGGY, "buggy.py")
    failed = [r["name"] for r in run["summary"]["results"] if r["outcome"] == "failed"]
    assert any("dividir" in n for n in failed)         # ZeroDivisionError detectado
    assert run["summary"]["passed"] > 0
    assert any(i["rule"] == "HARDCODED_SECRET" for i in run["issues"])
