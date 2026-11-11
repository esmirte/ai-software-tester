"""Execução isolada de testes (sandbox) com limites de tempo, memória e ambiente."""
from __future__ import annotations

import logging
import os
import shutil
import signal
import subprocess
import sys
import tempfile
import time
import xml.etree.ElementTree as ET
from pathlib import Path

from config import Settings
from core.models import GeneratedTest, RunSummary, TestResult

log = logging.getLogger("test_runner")
IGNORE = shutil.ignore_patterns(".git", "venv", ".venv", "__pycache__", "node_modules",
                                ".env", ".env.*", "*.pem", "*.key", "_ai_tests", ".pytest_cache")


class SandboxRunner:
    """Copia o projeto para um diretório temporário e roda o pytest isolado.

    Proteções: diretório temporário descartável, ambiente mínimo (sem credenciais),
    timeout, limites de CPU/memória (POSIX), grupo de processos próprio e,
    opcionalmente, Docker sem rede.
    """

    def __init__(self, settings: Settings):
        self.s = settings

    def run(self, project_dir: Path, tests: list[GeneratedTest]) -> RunSummary:
        sandbox = Path(tempfile.mkdtemp(prefix="aitester_"))
        try:
            shutil.copytree(project_dir, sandbox, ignore=IGNORE, dirs_exist_ok=True)
            tdir = sandbox / "_ai_tests"
            tdir.mkdir(exist_ok=True)
            for t in tests:
                (tdir / t.filename).write_text(t.code, encoding="utf-8")
            targets = {Path(t.filename).stem: t.target for t in tests}
            return self._execute(sandbox, targets)
        finally:
            shutil.rmtree(sandbox, ignore_errors=True)

    # ------------------------------------------------------------------
    def _command(self, sandbox: Path) -> list[str]:
        pytest_args = ["-m", "pytest", "_ai_tests", "-q", "-p", "no:cacheprovider",
                       "--junitxml=report.xml", "--tb=short"]
        if self.s.use_docker:
            return ["docker", "run", "--rm", "--network", "none",
                    "--memory", f"{self.s.memory_mb}m", "--cpus", "1", "--pids-limit", "128",
                    "--read-only", "--tmpfs", "/tmp", "-v", f"{sandbox}:/work", "-w", "/work",
                    self.s.docker_image, "python", *pytest_args]
        return [sys.executable, *pytest_args]

    def _env(self, sandbox: Path) -> dict[str, str]:
        env = {"PATH": os.environ.get("PATH", ""), "HOME": str(sandbox),
               "PYTHONDONTWRITEBYTECODE": "1", "PYTHONHASHSEED": "0"}
        for key in ("SYSTEMROOT", "TEMP", "TMP"):            # necessários no Windows
            if key in os.environ:
                env[key] = os.environ[key]
        return env                                           # nenhuma credencial é repassada

    def _limits(self):
        if os.name != "posix":
            return None
        import resource

        def apply() -> None:
            mem = self.s.memory_mb * 1024 * 1024
            resource.setrlimit(resource.RLIMIT_AS, (mem, mem))
            resource.setrlimit(resource.RLIMIT_CPU, (self.s.cpu_seconds, self.s.cpu_seconds))
            resource.setrlimit(resource.RLIMIT_FSIZE, (50 * 1024 * 1024,) * 2)
            resource.setrlimit(resource.RLIMIT_CORE, (0, 0))
        return apply

    def _execute(self, sandbox: Path, targets: dict[str, str]) -> RunSummary:
        cmd = self._command(sandbox)
        log.info("Executando em sandbox %s (docker=%s, timeout=%ss)", sandbox, self.s.use_docker, self.s.timeout_s)
        start = time.perf_counter()
        kwargs: dict = dict(cwd=sandbox, env=self._env(sandbox), stdout=subprocess.PIPE,
                            stderr=subprocess.STDOUT, text=True)
        if os.name == "posix":
            kwargs.update(start_new_session=True, preexec_fn=None if self.s.use_docker else self._limits())
        proc = subprocess.Popen(cmd, **kwargs)
        timed_out = False
        try:
            output, _ = proc.communicate(timeout=self.s.timeout_s)
        except subprocess.TimeoutExpired:
            timed_out = True
            if os.name == "posix":
                os.killpg(proc.pid, signal.SIGKILL)
            else:
                proc.kill()
            output, _ = proc.communicate()
            log.warning("Timeout de %ss excedido; processo encerrado.", self.s.timeout_s)
        duration = time.perf_counter() - start

        summary = self._parse_junit(sandbox / "report.xml", targets)
        summary.duration = round(duration, 3)
        summary.timed_out = timed_out
        summary.output = (output or "")[-8000:]
        log.info("Execução concluída: %d testes, %d falhas, %.2fs", summary.total, summary.failed, duration)
        return summary

    @staticmethod
    def _parse_junit(xml_path: Path, targets: dict[str, str]) -> RunSummary:
        summary = RunSummary()
        if not xml_path.exists():
            return summary
        for case in ET.parse(xml_path).getroot().iter("testcase"):
            outcome, message = "passed", ""
            for child in case:
                if child.tag in ("failure", "error", "skipped"):
                    outcome = "failed" if child.tag == "failure" else child.tag
                    message = (child.get("message") or "") + "\n" + (child.text or "")
            stem = case.get("classname", "").split(".")[-1]
            summary.results.append(TestResult(
                name=case.get("name", ""), outcome=outcome,
                duration=float(case.get("time", 0)), message=message.strip()[:1500],
                target=targets.get(stem, stem)))
        summary.total = len(summary.results)
        for r in summary.results:
            if r.outcome == "passed":
                summary.passed += 1
            elif r.outcome == "failed":
                summary.failed += 1
            elif r.outcome == "skipped":
                summary.skipped += 1
            else:
                summary.errors += 1
        return summary
