"""Testes do resgate por bundle JS e da fila de reavaliacao.

Roda com: python3 tests/test_bundle.py
"""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import analise  # noqa: E402
import coletor  # noqa: E402


def teste_bundle_conta_frequencia():
    cassino = ("casino " * 20) + ("slot " * 8) + ("odds " * 12) + "pix"
    ev = analise.evidencia_bundle(cassino)
    assert ev["forte"] is True
    assert ev["pontos"] >= 15, ev


def teste_bundle_ignora_loja_comum():
    loja = ("comprar agora bonus de desconto frete gratis " * 3) + "carrinho"
    ev = analise.evidencia_bundle(loja)
    assert ev["pontos"] == 0, ev


def teste_bundle_vazio_nao_quebra():
    ev = analise.evidencia_bundle("")
    assert ev["pontos"] == 0 and ev["forte"] is False


def teste_fila_reavaliacao_respeita_teto():
    conhecidos = {"bet%d.com" % i: {"d": "bet%d.com" % i, "pb": False, "st": "vivo",
                                    "visto": "2026-11-01"} for i in range(300)}
    conhecidos["aposta.bet.br"] = {"d": "aposta.bet.br", "pb": True, "st": "vivo",
                                   "visto": "2026-11-01"}
    fila = coletor.fila_reavaliacao(conhecidos, [], 100, fracao=0.3)
    assert len(fila) == 50, len(fila)
    assert all(c["dominio"] != "aposta.bet.br" for c in fila)


def teste_fila_reavaliacao_ignora_ja_pendente():
    conhecidos = {"bet1.com": {"d": "bet1.com", "pb": False, "st": "vivo", "visto": "2026-11-01"}}
    fila = coletor.fila_reavaliacao(conhecidos, [{"dominio": "bet1.com", "peso": 5}], 100)
    assert fila == []


if __name__ == "__main__":
    falhas = 0
    for nome, fn in sorted(list(globals().items())):
        if nome.startswith("teste_") and callable(fn):
            try:
                fn()
                print("ok  ", nome)
            except Exception as e:  # noqa: BLE001
                print("FALHA", nome, e)
                falhas += 1
    print("\n%d falha(s)" % falhas)
    sys.exit(1 if falhas else 0)
