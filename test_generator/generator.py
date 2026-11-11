"""Geração automática de testes Pytest a partir da análise estática."""
from __future__ import annotations

import ast
import itertools
from pathlib import Path

from core.models import FileAnalysis, FunctionInfo, GeneratedTest

# (valores válidos, casos extremos) como código-fonte Python
SAMPLES: dict[str, tuple[list[str], list[str]]] = {
    "int": (["1", "2"], ["0", "-1", "2**31", "-(2**31)"]),
    "float": (["1.5"], ["0.0", "-1.0", "1e308", "float('inf')", "float('nan')"]),
    "str": (["'abc'"], ["''", "' '", "'a' * 1000", "'ção ✓'"]),
    "bool": (["True", "False"], []),
    "list": (["[1, 2, 3]"], ["[]", "[None]"]),
    "dict": (["{'a': 1}"], ["{}"]),
    "tuple": (["(1, 2)"], ["()"]),
    "set": (["{1, 2}"], ["set()"]),
    "bytes": (["b'abc'"], ["b''"]),
}
GENERIC = (["1"], ["0", "-1", "None", "''", "[]"])
BASE_ALLOWED = {"ValueError", "TypeError"}
MAX_EDGE_CASES = 12


def _samples_for(annotation: str | None) -> tuple[list[str], list[str]]:
    if not annotation:
        return GENERIC
    base = annotation.split("[")[0].strip().lower()
    return SAMPLES.get(base, GENERIC)


class TestGenerator:
    """Gera arquivos de teste: existência, smoke (caminho feliz) e casos extremos."""
    __test__ = False

    def generate_for_project(self, analyses: list[FileAnalysis]) -> list[GeneratedTest]:
        tests = []
        for fa in analyses:
            if fa.syntax_ok and fa.functions:
                gt = self.generate_for_file(fa)
                if gt.n_tests:
                    tests.append(gt)
        return tests

    def generate_for_file(self, fa: FileAnalysis) -> GeneratedTest:
        stem = Path(fa.path).stem.replace("-", "_")
        rel_dir = str(Path(fa.path).parent).replace("\\", "/")
        header = f'''"""Testes gerados automaticamente para {fa.path}."""
import importlib.util
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / {rel_dir!r}))
_spec = importlib.util.spec_from_file_location("target_{stem}", ROOT / {fa.path!r})
mod = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(mod)
'''
        body, count = [], 0
        for fn in fa.functions:
            if fn.name.startswith("_") or any(a.startswith("*") for a in fn.args):
                continue
            chunk, n = self._tests_for_function(fn)
            body.append(chunk)
            count += n
        return GeneratedTest(f"test_{stem}.py", header + "".join(body), fa.path, count)

    def _tests_for_function(self, fn: FunctionInfo) -> tuple[str, int]:
        name = fn.name
        lines = [f"\n\ndef test_{name}_exists():\n    assert callable(mod.{name})\n"]
        count = 1
        valid, edge = [], []
        per_arg_valid, per_arg_edge = [], []
        for arg in fn.required_args:
            v, e = _samples_for(fn.annotations.get(arg))
            per_arg_valid.append(v)
            per_arg_edge.append(e)

        happy = [tuple(v[0] for v in per_arg_valid)]
        for combo in itertools.islice(itertools.product(*[v[:2] for v in per_arg_valid]), 4):
            valid.append(combo)
        valid = list(dict.fromkeys(happy + valid))
        for i, edges in enumerate(per_arg_edge):
            for ev in edges:
                args = [v[0] for v in per_arg_valid]
                args[i] = ev
                edge.append(tuple(args))
        edge = list(dict.fromkeys(edge))[:MAX_EDGE_CASES]

        def fmt(cases: list[tuple[str, ...]]) -> str:
            return ",\n        ".join("(" + "".join(f"{a}, " for a in c) + ")" for c in cases)

        if valid:
            lines.append(
                f"\n\n@pytest.mark.parametrize(\"args\", [\n        {fmt(valid)},\n])\n"
                f"def test_{name}_smoke(args):\n"
                f"    \"\"\"Caminho feliz: não deve lançar exceção com entradas válidas.\"\"\"\n"
                f"    mod.{name}(*args)\n")
            count += len(valid)
        if edge:
            allowed = sorted(BASE_ALLOWED | set(fn.raises))
            lines.append(
                f"\n\n@pytest.mark.parametrize(\"args\", [\n        {fmt(edge)},\n])\n"
                f"def test_{name}_edge_cases(args):\n"
                f"    \"\"\"Casos extremos: só exceções esperadas são toleradas.\"\"\"\n"
                f"    try:\n        mod.{name}(*args)\n"
                f"    except ({', '.join(allowed)}):\n        pass\n")
            count += len(edge)
        return "".join(lines), count

    @staticmethod
    def is_valid_python(code: str) -> bool:
        try:
            ast.parse(code)
            return True
        except SyntaxError:
            return False
