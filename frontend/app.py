"""Interface Streamlit.  Execute: streamlit run frontend/app.py"""
from __future__ import annotations

import sys
import tempfile
from dataclasses import replace
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

import pandas as pd  # noqa: E402
import streamlit as st  # noqa: E402

from config import Settings, setup_logging  # noqa: E402
from core.pipeline import QAPipeline  # noqa: E402

st.set_page_config(page_title="AI Software Tester", page_icon="🧪", layout="wide")

if "settings" not in st.session_state:
    st.session_state.settings = Settings()
    setup_logging(st.session_state.settings)
settings: Settings = st.session_state.settings
pipe = QAPipeline(settings)

PAGES = ["📊 Dashboard", "🔍 Análise de código", "🧬 Geração de testes", "▶️ Execução",
         "✅ Resultados", "📄 Relatórios", "🕘 Histórico", "⚙️ Configurações"]
page = st.sidebar.radio("Navegação", PAGES)
st.sidebar.caption("IA: " + ("ativa" if pipe.ai.available else "heurísticas locais"))


def materialize_source() -> Path | None:
    """Entrada de código (colar / enviar / pasta) -> diretório do projeto."""
    mode = st.radio("Origem do código", ["Colar código", "Enviar arquivos .py", "Caminho de uma pasta"], horizontal=True)
    settings.workspace_dir.mkdir(parents=True, exist_ok=True)
    if mode == "Colar código":
        code = st.text_area("Código Python", height=280, key="code_input",
                            placeholder="def dividir(a: int, b: int) -> float:\n    return a / b")
        if code.strip():
            d = Path(tempfile.mkdtemp(prefix="paste_", dir=settings.workspace_dir))
            (d / "snippet.py").write_text(code, encoding="utf-8")
            return d
    elif mode == "Enviar arquivos .py":
        files = st.file_uploader("Arquivos", type=["py"], accept_multiple_files=True)
        if files:
            d = Path(tempfile.mkdtemp(prefix="upload_", dir=settings.workspace_dir))
            for f in files:
                (d / Path(f.name).name).write_bytes(f.getvalue())
            return d
    else:
        p = st.text_input("Pasta do projeto (caminho completo)")
        if p and Path(p).is_dir():
            return Path(p)
        if p:
            st.error("Pasta não encontrada.")
    return None


def show_run_metrics(run: dict) -> None:
    s = run["summary"]
    cols = st.columns(6)
    for col, (name, val) in zip(cols, [("Total", s["total"]), ("Aprovados", s["passed"]),
                                       ("Reprovados", s["failed"] + s["errors"]), ("Ignorados", s["skipped"]),
                                       ("Aprovação", f'{s["pass_rate"]}%'), ("Tempo", f'{s["duration"]}s')]):
        col.metric(name, val)


# ----------------------------------------------------------------- páginas
if page == PAGES[0]:
    st.title("📊 Dashboard")
    runs = pipe.repo.list_runs()
    if not runs:
        st.info("Nenhuma execução ainda. Vá em **Execução** para começar.")
    else:
        df = pd.DataFrame(runs)
        c1, c2, c3 = st.columns(3)
        c1.metric("Execuções", len(df))
        c2.metric("Aprovação média", f"{df.pass_rate.mean():.1f}%")
        c3.metric("Falhas acumuladas", int(df.failed.sum()))
        st.subheader("Taxa de aprovação ao longo do tempo")
        st.line_chart(df.sort_values("id").set_index("id")["pass_rate"])
        st.dataframe(df, use_container_width=True, hide_index=True)

elif page == PAGES[1]:
    st.title("🔍 Análise de código")
    src = materialize_source()
    if src and st.button("Analisar", type="primary"):
        analyses = pipe.analyze(src)
        st.session_state.analyses, st.session_state.src = analyses, src
    if "analyses" in st.session_state:
        analyses = st.session_state.analyses
        rows = [{"arquivo": a.path, "severidade": i.severity, "categoria": i.category, "linha": i.line,
                 "regra": i.rule, "mensagem": i.message, "sugestão": i.suggestion}
                for a in analyses for i in a.issues]
        st.metric("Qualidade média", f"{sum(a.quality_score for a in analyses) / max(len(analyses), 1):.0f}/100")
        st.dataframe(pd.DataFrame(rows), use_container_width=True, hide_index=True) if rows \
            else st.success("Nenhum problema encontrado.")

elif page == PAGES[2]:
    st.title("🧬 Geração de testes")
    if "analyses" not in st.session_state:
        st.info("Faça a análise primeiro (página **Análise de código**).")
    else:
        if st.button("Gerar testes", type="primary"):
            st.session_state.tests = pipe.generate(st.session_state.src, st.session_state.analyses)
        for t in st.session_state.get("tests", []):
            with st.expander(f"{t.filename} — {t.n_tests} testes ({t.target})"):
                st.code(t.code, language="python")

elif page == PAGES[3]:
    st.title("▶️ Execução")
    label = st.text_input("Rótulo da execução (ex.: versão 1.2)")
    src = materialize_source()
    if src and st.button("🚀 Iniciar testes", type="primary"):
        with st.spinner("Analisando, gerando e executando em sandbox..."):
            st.session_state.run = pipe.run_project(src, label)
        st.success(f"Execução #{st.session_state.run['id']} concluída.")
    if "run" in st.session_state:
        show_run_metrics(st.session_state.run)

elif page == PAGES[4]:
    st.title("✅ Resultados")
    run = st.session_state.get("run")
    if not run:
        st.info("Execute os testes primeiro.")
    else:
        show_run_metrics(run)
        res = pd.DataFrame(run["summary"]["results"])
        if not res.empty:
            flt = st.multiselect("Filtrar", sorted(res.outcome.unique()), default=sorted(res.outcome.unique()))
            st.dataframe(res[res.outcome.isin(flt)][["name", "outcome", "target", "duration", "explanation", "suggestion"]],
                         use_container_width=True, hide_index=True)
        if run["summary"]["timed_out"]:
            st.error("A execução excedeu o tempo limite.")
        with st.expander("Saída bruta do pytest"):
            st.code(run["summary"]["output"])

elif page == PAGES[5]:
    st.title("📄 Relatórios")
    runs = pipe.repo.list_runs()
    if runs:
        rid = st.selectbox("Execução", [r["id"] for r in runs])
        run = pipe.repo.get(rid)
        html_doc = pipe.reporter.build_html(run)
        st.download_button("⬇️ Baixar HTML", html_doc, f"relatorio_{rid}.html", "text/html")
        pdf = pipe.reporter.build_pdf(run)
        if pdf:
            st.download_button("⬇️ Baixar PDF", pdf, f"relatorio_{rid}.pdf", "application/pdf")
        else:
            st.caption("Instale `reportlab` para exportar PDF.")
        st.components.v1.html(html_doc, height=700, scrolling=True)
    else:
        st.info("Sem execuções.")

elif page == PAGES[6]:
    st.title("🕘 Histórico")
    runs = pipe.repo.list_runs()
    st.dataframe(pd.DataFrame(runs), use_container_width=True, hide_index=True)
    if len(runs) >= 2:
        ids = [r["id"] for r in runs]
        c1, c2 = st.columns(2)
        a = c1.selectbox("Versão anterior", ids, index=min(1, len(ids) - 1))
        b = c2.selectbox("Versão nova", ids, index=0)
        if st.button("Comparar"):
            st.json(pipe.compare(a, b))

else:
    st.title("⚙️ Configurações")
    t = st.number_input("Timeout (s)", 5, 600, settings.timeout_s)
    m = st.number_input("Memória máxima (MB)", 64, 4096, settings.memory_mb)
    dk = st.checkbox("Usar Docker (sandbox forte, sem rede)", settings.use_docker)
    img = st.text_input("Imagem Docker (precisa ter pytest)", settings.docker_image)
    ai = st.checkbox("Usar IA generativa (requer ANTHROPIC_API_KEY)", settings.use_ai)
    model = st.text_input("Modelo", settings.ai_model)
    if st.button("Salvar"):
        st.session_state.settings = replace(settings, timeout_s=int(t), cpu_seconds=int(t), memory_mb=int(m),
                                            use_docker=dk, docker_image=img, use_ai=ai, ai_model=model)
        st.success("Configurações salvas.")
