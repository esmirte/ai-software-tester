"""Integração com modelos de IA (opcional) + heurísticas locais de fallback."""
from __future__ import annotations

import logging
import os
import re

log = logging.getLogger("ai_engine")

PLAIN_EXPLANATIONS = {
    "ZeroDivisionError": ("Houve uma divisão por zero.",
                          "Valide o divisor antes de dividir (ex.: `if b == 0: raise ValueError(...)`)."),
    "IndexError": ("Foi acessada uma posição inexistente de uma lista.",
                   "Verifique o tamanho da lista antes de acessar o índice."),
    "KeyError": ("Foi usada uma chave que não existe no dicionário.",
                 "Use `dict.get(chave, padrao)` ou valide a chave."),
    "AttributeError": ("Um objeto não possui o atributo usado (frequentemente é None).",
                       "Cheque se o valor não é None antes de usar seus atributos."),
    "NameError": ("Uma variável ou função foi usada sem ser definida.",
                  "Defina/importe o nome antes de usá-lo."),
    "UnboundLocalError": ("Uma variável local foi usada antes de receber valor.",
                          "Inicialize a variável em todos os caminhos do código."),
    "RecursionError": ("A função chamou a si mesma sem parar.",
                       "Garanta uma condição de parada na recursão."),
    "OverflowError": ("Um número ficou grande demais para a operação.",
                      "Limite o intervalo de entrada ou use tipos adequados."),
    "MemoryError": ("A função consumiu memória em excesso.",
                    "Processe os dados em partes ou limite o tamanho da entrada."),
    "AssertionError": ("Uma verificação (assert) falhou: o resultado difere do esperado.",
                       "Compare o valor obtido com o esperado e ajuste a lógica."),
    "TypeError": ("Foi usado um tipo de dado incompatível com a operação.",
                  "Valide os tipos de entrada."),
    "ValueError": ("Um valor inválido foi fornecido.", "Valide o valor antes de processá-lo."),
}


class AIEngine:
    """Usa um LLM (Anthropic) quando disponível; caso contrário, regras locais."""

    def __init__(self, enabled: bool = False, model: str = "claude-sonnet-5-5"):
        self.model = model
        self._client = None
        if enabled and os.getenv("ANTHROPIC_API_KEY"):
            try:
                import anthropic
                self._client = anthropic.Anthropic()
            except ImportError:
                log.warning("Pacote 'anthropic' não instalado; usando heurísticas locais.")

    @property
    def available(self) -> bool:
        return self._client is not None

    def _ask(self, prompt: str, max_tokens: int = 1200) -> str:
        msg = self._client.messages.create(
            model=self.model, max_tokens=max_tokens,
            system="Você é um engenheiro de QA sênior. Responda em português, de forma objetiva.",
            messages=[{"role": "user", "content": prompt}])
        return "".join(b.text for b in msg.content if getattr(b, "type", "") == "text").strip()

    # ------------------------------------------------------------------
    def explain_failure(self, test_name: str, message: str, source: str = "") -> tuple[str, str]:
        """Retorna (explicação em linguagem simples, sugestão de correção)."""
        if self.available:
            try:
                text = self._ask(
                    f"Teste que falhou: {test_name}\nErro:\n{message[:1500]}\n\nCódigo:\n{source[:4000]}\n\n"
                    "Explique a causa em 2 frases simples e sugira a correção (com trecho de código curto). "
                    "Formato: EXPLICAÇÃO: ... SUGESTÃO: ...")
                m = re.search(r"EXPLICA[ÇC][ÃA]O:\s*(.*?)\s*SUGEST[ÃA]O:\s*(.*)", text, re.S | re.I)
                if m:
                    return m.group(1).strip(), m.group(2).strip()
                return text, ""
            except Exception as exc:  # noqa: BLE001 - qualquer falha de rede cai no fallback
                log.warning("Falha ao consultar IA: %s", exc)
        for exc_name, (why, fix) in PLAIN_EXPLANATIONS.items():
            if exc_name in message:
                return why, fix
        return "O teste falhou; veja a mensagem de erro para detalhes.", "Revise a lógica da função testada."

    def suggest_tests(self, source: str) -> str | None:
        """Pede ao LLM testes pytest adicionais (retorna None sem IA)."""
        if not self.available:
            return None
        try:
            text = self._ask(
                "Escreva testes pytest adicionais (casos extremos e regras de negócio) para o código abaixo. "
                "O módulo alvo já está carregado na variável global `mod`. "
                "Retorne apenas funções `def test_...():` que usem `mod`.\n\n" + source[:6000],
                max_tokens=2000)
            return re.sub(r"^```(?:python)?\s*|\s*```$", "", text.strip(), flags=re.M)
        except Exception as exc:  # noqa: BLE001
            log.warning("Falha ao gerar testes via IA: %s", exc)
            return None
