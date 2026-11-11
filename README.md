# AI Software Tester

Plataforma de QA automatizada: analisa código Python, gera testes Pytest, executa em sandbox,
explica falhas e produz relatórios (HTML/PDF) com histórico em SQLite.

## Instalação
```bash
python -m venv .venv
.venv\Scripts\activate          # Windows   (Linux/macOS: source .venv/bin/activate)
pip install -r requirements.txt
```

## Uso
```bash
streamlit run frontend/app.py          # interface gráfica
uvicorn api.main:app --reload          # API  -> http://127.0.0.1:8000/docs
pytest                                 # testes do próprio sistema
```

## IA generativa (opcional)
```bash
set ANTHROPIC_API_KEY=sua_chave        # Windows (Linux/macOS: export ...)
```
Depois marque "Usar IA generativa" em Configurações. Sem chave, o sistema usa heurísticas locais.

## Segurança do sandbox
- Projeto copiado para pasta temporária descartável (sem .env, .git, chaves).
- Ambiente mínimo: nenhuma variável de ambiente/credencial é repassada.
- Timeout + limites de CPU/memória/tamanho de arquivo (Linux/macOS).
- No Windows os limites de memória/CPU não existem: use Docker (Configurações > Docker).
- Docker: `--network none --read-only --pids-limit`. Imagem de exemplo:
  `echo "FROM python:3.12-slim\nRUN pip install pytest" | docker build -t ai-tester-sandbox -`

## Próximos passos
Testes de API/Selenium/Playwright, regressão por snapshot, correção automática com reexecução.
