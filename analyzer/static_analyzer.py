"""Análise estática de código Python baseada em AST."""
from __future__ import annotations

import ast
import re
from pathlib import Path

from core.models import FileAnalysis, FunctionInfo, Issue

SECRET_RE = re.compile(r"(password|passwd|secret|token|api_?key)", re.I)
PENALTY = {"error": 10, "warning": 4, "info": 1}
IGNORED_DIRS = {".git", "venv", ".venv", "__pycache__", "node_modules", "_ai_tests", ".pytest_cache"}


class StaticAnalyzer:
    """Analisa arquivos .py: erros de sintaxe, bugs, segurança e desempenho."""

    def analyze_project(self, root: Path) -> list[FileAnalysis]:
        files = [p for p in sorted(root.rglob("*.py"))
                 if not (set(p.relative_to(root).parts) & IGNORED_DIRS)
                 and not p.name.startswith("test_")]
        return [self.analyze_file(p, root) for p in files]

    def analyze_file(self, path: Path, root: Path) -> FileAnalysis:
        rel = str(path.relative_to(root)).replace("\\", "/")
        source = path.read_text(encoding="utf-8", errors="replace")
        return self.analyze_source(source, rel)

    def analyze_source(self, source: str, rel: str) -> FileAnalysis:
        lines = len(source.splitlines())
        try:
            tree = ast.parse(source)
        except SyntaxError as exc:
            issue = Issue(rel, exc.lineno or 0, "error", "syntax", "SYNTAX",
                          f"Erro de sintaxe: {exc.msg}", "Corrija a sintaxe indicada.")
            return FileAnalysis(rel, lines, False, 0.0, [], [issue])

        issues: list[Issue] = []
        functions: list[FunctionInfo] = []
        for node in ast.walk(tree):
            issues.extend(self._check_node(node, rel))
        for node in tree.body:
            if isinstance(node, ast.FunctionDef):
                info = self._function_info(node)
                functions.append(info)
                issues.extend(self._check_function(node, info, rel))
        issues.extend(self._check_loops(tree, rel))
        score = max(0.0, 100.0 - sum(PENALTY[i.severity] for i in issues))
        return FileAnalysis(rel, lines, True, score, functions, issues)

    # ---------- extração ----------
    @staticmethod
    def _function_info(fn: ast.FunctionDef) -> FunctionInfo:
        a = fn.args
        positional = [x.arg for x in a.posonlyargs + a.args]
        n_req = len(positional) - len(a.defaults)
        raises: set[str] = set()
        complexity = 1
        for n in ast.walk(fn):
            if isinstance(n, ast.Raise) and n.exc is not None:
                exc = n.exc.func if isinstance(n.exc, ast.Call) else n.exc
                if isinstance(exc, ast.Name):
                    raises.add(exc.id)
                elif isinstance(exc, ast.Attribute):
                    raises.add(exc.attr)
            if isinstance(n, (ast.If, ast.For, ast.While, ast.Try, ast.ExceptHandler,
                              ast.BoolOp, ast.IfExp, ast.comprehension)):
                complexity += 1
        end = getattr(fn, "end_lineno", fn.lineno) or fn.lineno
        ann = {x.arg: ast.unparse(x.annotation) for x in a.posonlyargs + a.args if x.annotation}
        return FunctionInfo(
            name=fn.name, lineno=fn.lineno, args=positional,
            required_args=positional[:n_req], annotations=ann,
            returns=ast.unparse(fn.returns) if fn.returns else None,
            raises=sorted(raises), complexity=complexity,
            length=end - fn.lineno + 1, has_docstring=ast.get_docstring(fn) is not None,
        )

    # ---------- regras ----------
    def _check_node(self, node: ast.AST, rel: str) -> list[Issue]:
        out: list[Issue] = []
        line = getattr(node, "lineno", 0)
        if isinstance(node, ast.ExceptHandler):
            if node.type is None:
                out.append(Issue(rel, line, "warning", "bug", "BARE_EXCEPT",
                                 "'except:' genérico engole todos os erros.",
                                 "Capture exceções específicas."))
            if len(node.body) == 1 and isinstance(node.body[0], ast.Pass):
                out.append(Issue(rel, line, "warning", "bug", "SWALLOWED_EXCEPTION",
                                 "Exceção ignorada silenciosamente (pass).",
                                 "Registre o erro em log ou trate-o."))
        elif isinstance(node, ast.Call):
            name = self._call_name(node)
            if name in {"eval", "exec"}:
                out.append(Issue(rel, line, "error", "security", "EVAL_EXEC",
                                 f"Uso de {name}() permite execução de código arbitrário.",
                                 "Use ast.literal_eval ou evite execução dinâmica."))
            if name in {"os.system", "os.popen"}:
                out.append(Issue(rel, line, "warning", "security", "OS_COMMAND",
                                 f"{name}() é vulnerável a injeção de comandos.",
                                 "Use subprocess.run com lista de argumentos."))
            if name.startswith("subprocess.") and any(
                    k.arg == "shell" and isinstance(k.value, ast.Constant) and k.value.value is True
                    for k in node.keywords):
                out.append(Issue(rel, line, "error", "security", "SHELL_TRUE",
                                 "subprocess com shell=True.", "Passe uma lista e shell=False."))
            if name in {"pickle.loads", "pickle.load"}:
                out.append(Issue(rel, line, "warning", "security", "PICKLE",
                                 "Desserializar pickle de fonte não confiável é perigoso.",
                                 "Use JSON ou outro formato seguro."))
            if name in {"hashlib.md5", "hashlib.sha1"}:
                out.append(Issue(rel, line, "warning", "security", "WEAK_HASH",
                                 f"{name} é um hash fraco.", "Use SHA-256 ou superior."))
        elif isinstance(node, ast.Assign):
            for t in node.targets:
                if (isinstance(t, ast.Name) and SECRET_RE.search(t.id)
                        and isinstance(node.value, ast.Constant)
                        and isinstance(node.value.value, str) and node.value.value):
                    out.append(Issue(rel, line, "error", "security", "HARDCODED_SECRET",
                                     f"Credencial fixa no código: '{t.id}'.",
                                     "Use variáveis de ambiente ou um cofre de segredos."))
        elif isinstance(node, ast.Compare):
            for op, comp in zip(node.ops, node.comparators):
                if isinstance(op, (ast.Eq, ast.NotEq)) and isinstance(comp, ast.Constant) and comp.value is None:
                    out.append(Issue(rel, line, "info", "style", "NONE_COMPARE",
                                     "Comparação com None usando ==/!=.", "Use 'is None' / 'is not None'."))
        return out

    def _check_function(self, fn: ast.FunctionDef, info: FunctionInfo, rel: str) -> list[Issue]:
        out: list[Issue] = []
        for d in fn.args.defaults + [d for d in fn.args.kw_defaults if d is not None]:
            if isinstance(d, (ast.List, ast.Dict, ast.Set)):
                out.append(Issue(rel, fn.lineno, "error", "bug", "MUTABLE_DEFAULT",
                                 f"Argumento padrão mutável em '{fn.name}'.",
                                 "Use None e crie o objeto dentro da função."))
        if info.complexity > 10:
            out.append(Issue(rel, fn.lineno, "warning", "style", "HIGH_COMPLEXITY",
                             f"'{fn.name}' tem complexidade {info.complexity}.",
                             "Divida a função em partes menores."))
        if info.length > 50:
            out.append(Issue(rel, fn.lineno, "info", "style", "LONG_FUNCTION",
                             f"'{fn.name}' tem {info.length} linhas.", "Refatore em funções menores."))
        if len(info.args) > 6:
            out.append(Issue(rel, fn.lineno, "info", "style", "MANY_ARGS",
                             f"'{fn.name}' recebe {len(info.args)} argumentos.", "Agrupe em um objeto/dataclass."))
        if not info.has_docstring and not fn.name.startswith("_"):
            out.append(Issue(rel, fn.lineno, "info", "style", "NO_DOCSTRING",
                             f"'{fn.name}' sem docstring.", "Documente o propósito da função."))
        return out

    def _check_loops(self, tree: ast.AST, rel: str) -> list[Issue]:
        out: list[Issue] = []

        def walk(n: ast.AST, d: int = 0) -> None:
            for c in ast.iter_child_nodes(n):
                is_loop = isinstance(c, (ast.For, ast.While))
                nd = d + 1 if is_loop else d
                if is_loop and nd >= 3:
                    out.append(Issue(rel, c.lineno, "warning", "performance", "NESTED_LOOPS",
                                     "Três ou mais laços aninhados (custo O(n³)+).",
                                     "Reavalie o algoritmo ou use estruturas como dict/set."))
                if (isinstance(c, ast.For) and isinstance(c.iter, ast.Call)
                        and self._call_name(c.iter) == "range" and c.iter.args
                        and isinstance(c.iter.args[0], ast.Call)
                        and self._call_name(c.iter.args[0]) == "len"):
                    out.append(Issue(rel, c.lineno, "info", "performance", "RANGE_LEN",
                                     "range(len(...)) é pouco idiomático.",
                                     "Use enumerate() ou itere diretamente."))
                walk(c, nd)
        walk(tree)
        return out

    @staticmethod
    def _call_name(node: ast.Call) -> str:
        f = node.func
        if isinstance(f, ast.Name):
            return f.id
        if isinstance(f, ast.Attribute) and isinstance(f.value, ast.Name):
            return f"{f.value.id}.{f.attr}"
        return ""
