"""Geração de relatórios HTML e PDF."""
from __future__ import annotations

import html
from io import BytesIO
from typing import Any

CSS = """body{font-family:Segoe UI,Arial,sans-serif;margin:32px;color:#1f2937}
h1{margin-bottom:0}.muted{color:#6b7280}.grid{display:flex;gap:12px;flex-wrap:wrap;margin:16px 0}
.card{background:#f3f4f6;border-radius:10px;padding:12px 18px;min-width:130px}
.card b{display:block;font-size:24px}.ok{color:#059669}.bad{color:#dc2626}
table{border-collapse:collapse;width:100%;margin:12px 0}th,td{border:1px solid #e5e7eb;padding:6px 10px;text-align:left;font-size:14px}
th{background:#f9fafb}pre{background:#111827;color:#e5e7eb;padding:10px;border-radius:8px;overflow:auto;font-size:12px}"""


def _e(x: Any) -> str:
    return html.escape(str(x))


class ReportBuilder:
    def build_html(self, run: dict[str, Any]) -> str:
        s = run["summary"]
        rate_cls = "ok" if s["pass_rate"] >= 80 else "bad"
        cards = [("Total", s["total"]), ("Aprovados", s["passed"]), ("Reprovados", s["failed"] + s["errors"]),
                 ("Ignorados", s["skipped"]), ("Aprovação", f'<span class="{rate_cls}">{s["pass_rate"]}%</span>'),
                 ("Tempo", f'{s["duration"]}s')]
        cards_html = "".join(f'<div class="card">{n}<b>{v}</b></div>' for n, v in cards)

        fails = [r for r in s["results"] if r["outcome"] in ("failed", "error")]
        fail_rows = "".join(
            f"<tr><td>{_e(r['name'])}</td><td>{_e(r['target'])}</td><td>{_e(r.get('explanation',''))}</td>"
            f"<td>{_e(r.get('suggestion',''))}</td></tr>" for r in fails) or '<tr><td colspan="4">Nenhuma falha 🎉</td></tr>'
        issues = run.get("issues", [])
        issue_rows = "".join(
            f"<tr><td>{_e(i['severity'])}</td><td>{_e(i['file'])}:{i['line']}</td><td>{_e(i['rule'])}</td>"
            f"<td>{_e(i['message'])}</td><td>{_e(i['suggestion'])}</td></tr>" for i in issues) \
            or '<tr><td colspan="5">Nenhum problema estático encontrado.</td></tr>'
        recs = "".join(f"<li>{_e(r)}</li>" for r in run.get("recommendations", []))
        files = ", ".join(_e(f) for f in run.get("files_affected", [])) or "—"
        timeout = '<p class="bad">⚠ A execução excedeu o tempo limite e foi interrompida.</p>' if s.get("timed_out") else ""
        return f"""<!doctype html><html lang="pt-BR"><head><meta charset="utf-8">
<title>Relatório de QA #{_e(run.get('id', ''))}</title><style>{CSS}</style></head><body>
<h1>Relatório de QA</h1><p class="muted">{_e(run.get('label',''))} · {_e(run['created_at'])} · {_e(run.get('project',''))}</p>
{timeout}<div class="grid">{cards_html}</div>
<h2>Qualidade do código: {run.get('quality_score', 0):.0f}/100</h2>
<h2>Arquivos afetados</h2><p>{files}</p>
<h2>Testes reprovados</h2><table><tr><th>Teste</th><th>Arquivo</th><th>Explicação</th><th>Sugestão</th></tr>{fail_rows}</table>
<h2>Análise estática</h2><table><tr><th>Sev.</th><th>Local</th><th>Regra</th><th>Mensagem</th><th>Sugestão</th></tr>{issue_rows}</table>
<h2>Recomendações</h2><ul>{recs}</ul></body></html>"""

    def build_pdf(self, run: dict[str, Any]) -> bytes | None:
        """Gera PDF com reportlab; retorna None se a biblioteca não estiver instalada."""
        try:
            from reportlab.lib.pagesizes import A4
            from reportlab.lib.styles import getSampleStyleSheet
            from reportlab.platypus import Paragraph, SimpleDocTemplate, Spacer
        except ImportError:
            return None
        st = getSampleStyleSheet()
        s = run["summary"]
        buf = BytesIO()
        doc = SimpleDocTemplate(buf, pagesize=A4, title="Relatório de QA")
        P = lambda t, style="BodyText": Paragraph(_e(t), st[style])  # noqa: E731
        story = [P("Relatório de QA", "Title"), P(f"{run.get('label','')} - {run['created_at']}"), Spacer(1, 12),
                 P(f"Total: {s['total']} | Aprovados: {s['passed']} | Reprovados: {s['failed'] + s['errors']} | "
                   f"Ignorados: {s['skipped']} | Aprovação: {s['pass_rate']}% | Tempo: {s['duration']}s"),
                 P(f"Qualidade do código: {run.get('quality_score', 0):.0f}/100"), Spacer(1, 12),
                 P("Testes reprovados", "Heading2")]
        fails = [r for r in s["results"] if r["outcome"] in ("failed", "error")]
        story += [P(f"- {r['name']} ({r['target']}): {r.get('explanation','')} {r.get('suggestion','')}") for r in fails] \
            or [P("Nenhuma falha.")]
        story += [Spacer(1, 12), P("Problemas estáticos", "Heading2")]
        story += [P(f"[{i['severity']}] {i['file']}:{i['line']} {i['message']}") for i in run.get("issues", [])[:60]] \
            or [P("Nenhum problema encontrado.")]
        story += [Spacer(1, 12), P("Recomendações", "Heading2")] + [P(f"- {r}") for r in run.get("recommendations", [])]
        doc.build(story)
        return buf.getvalue()
