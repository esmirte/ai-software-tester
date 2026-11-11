"""API FastAPI.  Execute: uvicorn api.main:app --reload"""
from __future__ import annotations

from pathlib import Path

from fastapi import FastAPI, HTTPException
from fastapi.responses import HTMLResponse, Response
from pydantic import BaseModel, Field

from config import Settings, setup_logging
from core.pipeline import QAPipeline

settings = Settings()
setup_logging(settings)
pipeline = QAPipeline(settings)
app = FastAPI(title="AI Software Tester", version="1.0.0")


class CodeRequest(BaseModel):
    code: str = Field(min_length=1, max_length=200_000)
    filename: str = "snippet.py"
    label: str = ""


class ProjectRequest(BaseModel):
    path: str
    label: str = ""


@app.get("/health")
def health() -> dict:
    return {"status": "ok", "ai_enabled": pipeline.ai.available}


@app.post("/analyze")
def analyze(req: CodeRequest) -> dict:
    fa = pipeline.analyzer.analyze_source(req.code, req.filename)
    return {"quality_score": fa.quality_score, "syntax_ok": fa.syntax_ok,
            "issues": [i.__dict__ for i in fa.issues], "functions": [f.__dict__ for f in fa.functions]}


@app.post("/run/code")
def run_code(req: CodeRequest) -> dict:
    return pipeline.run_code(req.code, req.filename, req.label)


@app.post("/run/project")
def run_project(req: ProjectRequest) -> dict:
    target = Path(req.path).resolve()
    allowed = settings.workspace_dir.resolve()
    if allowed not in target.parents and target != allowed:          # controle de permissões
        raise HTTPException(403, f"Só é permitido analisar projetos dentro de {allowed}")
    if not target.is_dir():
        raise HTTPException(404, "Diretório não encontrado.")
    return pipeline.run_project(target, req.label)


@app.get("/runs")
def list_runs() -> list[dict]:
    return pipeline.repo.list_runs()


@app.get("/runs/{run_id}")
def get_run(run_id: int) -> dict:
    run = pipeline.repo.get(run_id)
    if not run:
        raise HTTPException(404, "Execução não encontrada.")
    return run


@app.get("/runs/{run_id}/report.html", response_class=HTMLResponse)
def report_html(run_id: int) -> str:
    return pipeline.reporter.build_html(get_run(run_id))


@app.get("/runs/{run_id}/report.pdf")
def report_pdf(run_id: int) -> Response:
    pdf = pipeline.reporter.build_pdf(get_run(run_id))
    if pdf is None:
        raise HTTPException(501, "Instale 'reportlab' para gerar PDF.")
    return Response(pdf, media_type="application/pdf")


@app.get("/compare")
def compare(a: int, b: int) -> dict:
    try:
        return pipeline.compare(a, b)
    except KeyError as exc:
        raise HTTPException(404, str(exc)) from exc
