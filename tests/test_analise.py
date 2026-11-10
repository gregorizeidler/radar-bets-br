"""Testes da análise. Roda com: python3 tests/test_analise.py"""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import analise  # noqa: E402

AUTORIZADAS = {
    "empresas": [
        {"empresa": "BPX BETS", "cnpj": "55.590.815/0001-60",
         "marcas": ["VAIDEBET", "BETPIX365"], "dominios": ["vaidebet.bet.br"]},
        {"empresa": "BETANO", "cnpj": "00.000.000/0001-00",
         "marcas": ["BETANO"], "dominios": ["betano.bet.br"]},
        {"empresa": "GENERICA", "cnpj": "11.111.111/0001-11",
         "marcas": ["CASSINO"], "dominios": ["cassino.bet.br"]},
    ]
}


def teste_sinais_detectam_casa_de_aposta():
    html = ("<title>Fortune Tiger</title> Cassino online com rodada gratis. "
            "Jogue slots da PG Soft e faca o saque via Pix.")
    r = analise.sinais_de_bet(html)
    assert r["parece_bet"] is True, r
    assert r["pontos"] >= 8


def teste_palavra_dentro_de_outra_palavra_nao_conta():
    html = ("Better Business Bureau between us. Nothing about gambling here, "
            "just a better page about betting companies in theory.")
    r = analise.sinais_de_bet(html)
    assert r["parece_bet"] is False, r


def teste_kit_igual_para_paginas_iguais():
    a = '<title>Bet 30</title><script src="/static/app.4f2a.js"></script><link href="/x/main.css">'
    b = '<title>Bet 300</title><script src="/static/app.4f2a.js"></script><link href="/x/main.css">'
    assert analise.impressao_kit(a) == analise.impressao_kit(b)
    c = '<title>Outra</title><script src="/outro/app.js"></script>'
    assert analise.impressao_kit(c) != analise.impressao_kit(a)


def teste_analytics_extrai_ids_reais():
    html = ('<script>GTM-ABC1234</script><script>G-ABCDEF12345</script>'
            'gtag("config","UA-1234567-1") fbq("init","123456789012345")')
    ids = analise.ids_analytics(html)
    assert "GTM-ABC1234" in ids
    assert "G-ABCDEF12345" in ids
    assert "UA-1234567-1" in ids
    assert "fbq:123456789012345" in ids


def teste_autorizada_exata():
    r = analise.parecido_com_autorizada("vaidebet.bet.br", AUTORIZADAS)
    assert r["rotulo"] == "autorizada", r


def teste_clone_por_marca_em_outro_dominio():
    r = analise.parecido_com_autorizada("vaidebet.com", AUTORIZADAS)
    assert r["rotulo"] == "clone_de_autorizada", r


def teste_clone_por_um_caractere():
    r = analise.parecido_com_autorizada("betanoo.bet.br", AUTORIZADAS)
    assert r["rotulo"] == "clone_de_autorizada", r


def teste_marca_generica_nao_vira_clone():
    # "cassino" é palavra comum: domínio com cassino no nome não é clone
    r = analise.parecido_com_autorizada("meucassinoonline.com", AUTORIZADAS)
    assert r["rotulo"] == "sem_registro", r


def teste_sem_registro():
    r = analise.parecido_com_autorizada("plataformaqualquer.xyz", AUTORIZADAS)
    assert r["rotulo"] == "sem_registro", r


def teste_ip_de_cdn_nao_agrupa():
    a = {"d": "a.com", "ip": ["104.21.1.1"], "k": "", "g": [], "ns": []}
    b = {"d": "b.com", "ip": ["104.21.1.1"], "k": "", "g": [], "ns": []}
    grupos = analise.clusters([a, b])
    assert len(grupos) == 2, grupos


def teste_kit_compartilhado_agrupa():
    a = {"d": "a.com", "ip": [], "k": "abc", "g": [], "ns": []}
    b = {"d": "b.com", "ip": [], "k": "abc", "g": [], "ns": []}
    grupos = analise.clusters([a, b])
    assert len(grupos) == 1, grupos


if __name__ == "__main__":
    falhas = 0
    for nome, fn in sorted(globals().items()):
        if nome.startswith("teste_") and callable(fn):
            try:
                fn()
                print("ok   " + nome)
            except AssertionError as e:
                falhas += 1
                print("FALHA " + nome + ": " + str(e))
    print("\n%d falha(s)" % falhas)
    sys.exit(1 if falhas else 0)
