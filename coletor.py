"""Radar de bets: pipeline diário.

Fontes, todas públicas e sem chave:
  1. Lista oficial de operadoras autorizadas (SPA/Ministério da Fazenda).
  2. Três índices de domínios vivos: Tranco, Majestic Million e Cisco Umbrella.
  3. Certificate Transparency (crt.sh): domínios com certificado novo.

Para cada candidato: resolve DNS, faz UM GET na home (sem login, sem cadastro,
sem tocar em página de depósito), mede os sinais de casa de aposta, calcula a
impressão digital do kit (arquivos estáticos + título), extrai IDs de analytics
e compara o nome com as marcas autorizadas.
"""
import csv
import io
import json
import os
import re
import statistics
import time
import zipfile
from concurrent.futures import ThreadPoolExecutor

import fontes
import analise

RAIZ = os.path.dirname(os.path.abspath(__file__))
DATA = os.path.join(RAIZ, "data")
DOCS = os.path.join(RAIZ, "docs", "dados")

TERMOS_CRT = ["%.bet.br", "%.bet"]

INDICES = [
    ("tranco", "https://tranco-list.eu/top-1m.csv.zip"),
    ("majestic", "https://downloads.majestic.com/majestic_million.csv"),
    ("umbrella", "http://s3-us-west-1.amazonaws.com/umbrella-static/top-1m.csv.zip"),
]

# token de aposta no nome do domínio (só pré-filtro; quem decide é a página)
TOKEN = re.compile(r"(bet|aposta|cassino|casino|tigrinho|tigre|aviator|blaze|"
                   r"slot|roleta|bingo|jackpot|loteria|odds|sorte|premio|"
                   r"azar|jogo)", re.I)
# palavras com "bet" dentro que não têm nada a ver
RUIM = re.compile(r"(better|alphabet|bethesda|betty|elizabeth|alberto|albert|"
                  r"betsy|booking|tubet|abeto|interpret|boston|bento|"
                  r"potente|betume|abet)", re.I)
FORTE = re.compile(r"(^bet|^aposta|^cassino|^casino|tigrinho|aviator|blaze|"
                   r"slot|roleta|bingo|jackpot|bet[0-9]|[0-9]bet|-bet|bet-)", re.I)

EXCLUIR_HOSTS = {"bethesda.net", "betterhelp.com", "forebet.com"}


def ler_json(caminho, padrao=None):
    try:
        with open(caminho, encoding="utf-8") as f:
            return json.load(f)
    except Exception:  # noqa: BLE001
        return padrao


def salvar_json(caminho, dados):
    os.makedirs(os.path.dirname(caminho), exist_ok=True)
    tmp = caminho + ".tmp"
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(dados, f, ensure_ascii=False, separators=(",", ":"))
        f.write("\n")
    os.replace(tmp, caminho)


def universo(dias_cache=7, verbose=True):
    """Três índices públicos de domínios vivos, em cache local de uma semana."""
    cache = os.path.join(DATA, "universo.txt")
    if os.path.exists(cache) and time.time() - os.path.getmtime(cache) < dias_cache * 86400:
        with open(cache, encoding="utf-8") as f:
            return [l.strip() for l in f if l.strip()]

    vistos = set()
    for nome, url in INDICES:
        try:
            bruto, _, _ = fontes.baixar(url, timeout=240, tentativas=2)
            if url.endswith(".zip"):
                with zipfile.ZipFile(io.BytesIO(bruto)) as z:
                    arquivo = [n for n in z.namelist() if n.endswith(".csv")][0]
                    texto = z.read(arquivo).decode("utf-8", "ignore")
                linhas = texto.splitlines()
                dominios = [l.split(",", 1)[1] for l in linhas if "," in l]
            else:
                texto = bruto.decode("utf-8", "ignore")
                leitor = csv.DictReader(io.StringIO(texto))
                dominios = [r.get("Domain", "") for r in leitor]
            for d in dominios:
                d = d.strip().lower()
                if d and " " not in d:
                    vistos.add(d)
            if verbose:
                print("indice %s: %d dominios" % (nome, len(dominios)))
        except Exception as e:  # noqa: BLE001
            if verbose:
                print("indice %s falhou: %s" % (nome, str(e)[:80]))
    lista = sorted(vistos)
    os.makedirs(DATA, exist_ok=True)
    with open(cache, "w", encoding="utf-8") as f:
        f.write("\n".join(lista))
    return lista


def peso_nome(dominio):
    sld = analise.sld(dominio)
    ponto = 1
    if dominio.endswith(".bet") or dominio.endswith(".bet.br"):
        ponto += 10
    if FORTE.search(sld):
        ponto += 6
    if "bet" in sld:
        ponto += 3
    if "aposta" in sld or "cassino" in sld or "casino" in sld:
        ponto += 3
    if dominio.endswith(".br"):
        ponto += 6
    return ponto


def candidatos(dominios, autorizadas, limite=None):
    oficiais = {d.lower() for e in autorizadas["empresas"] for d in e["dominios"]}
    fila = []
    for d in dominios:
        d = d.lower().strip()
        if not d or d in EXCLUIR_HOSTS or d in oficiais:
            continue
        if d.endswith((".gov.br", ".edu.br", ".gov", ".mil.br", ".mil")):
            continue
        alvo = analise.sld(d)
        if len(alvo) < 3 or RUIM.search(alvo) or not TOKEN.search(alvo):
            continue
        fila.append({"dominio": d, "peso": peso_nome(d), "origem": "indice"})
    fila.sort(key=lambda x: (-x["peso"], x["dominio"]))
    return fila[:limite] if limite else fila


def candidatos_por_certificado(autorizadas, dias=60):
    oficiais = {d.lower() for e in autorizadas["empresas"] for d in e["dominios"]}
    vistos, erros = {}, []
    def um(termo):
        try:
            return termo, fontes.certificados(termo, dias=100000)
        except Exception as e:  # noqa: BLE001
            return termo, e
    betbr = set()
    with ThreadPoolExecutor(max_workers=2) as ex:
        for termo, res in ex.map(um, TERMOS_CRT):
            if isinstance(res, Exception):
                erros.append({"termo": termo, "erro": str(res)[:120]})
                continue
            for c in res:
                vistos.setdefault(c["dominio"], c["emissao"])
                if c["dominio"].endswith(".bet.br"):
                    betbr.add(c["dominio"])
    if not vistos:
        return [], erros, None
    referencia = max(vistos.values())
    corte = time.mktime(time.strptime(referencia, "%Y-%m-%d")) - dias * 86400
    recentes = []
    for d, emissao in vistos.items():
        if d in oficiais or not d:
            continue
        try:
            ts = time.mktime(time.strptime(emissao, "%Y-%m-%d"))
        except Exception:  # noqa: BLE001
            continue
        if ts >= corte:
            recentes.append({"dominio": d, "peso": peso_nome(d) + 4,
                             "origem": "certificado", "emissao": emissao})
    # .bet.br é registro restrito a operadora autorizada: entra inteiro,
    # independente da data do certificado.
    ja = {x["dominio"] for x in recentes}
    for d in sorted(betbr):
        if d in oficiais or d in ja:
            continue
        recentes.append({"dominio": d, "peso": peso_nome(d) + 12,
                         "origem": "bet.br", "emissao": vistos.get(d, "")})
    recentes.sort(key=lambda x: (-x["peso"], x["dominio"]))
    return recentes, erros, referencia


def verificar(item, autorizadas, timeout=7):
    d = item["dominio"]
    info = fontes.dns(d, timeout=5)
    registro = {"d": d, "origem": item.get("origem", ""), "ip": info["a"][:4],
                "ns": [n.lower() for n in info["ns"][:4]],
                "visto": time.strftime("%Y-%m-%d"), "st": "morto", "p": 0,
                "s": [], "pf": [], "pb": False, "k": "", "g": [], "t": "",
                "sv": "", "ht": 0}
    pag = fontes.pagina(d, timeout=timeout) if info["a"] else None
    if pag:
        sinais = analise.sinais_de_bet(pag["html"])
        registro.update({"st": "vivo", "ht": pag["status"], "p": sinais["pontos"],
                         "s": sinais["sinais"], "pf": sinais["fortes"][:6],
                         "pb": sinais["parece_bet"],
                         "k": analise.impressao_kit(pag["html"]),
                         "g": analise.ids_analytics(pag["html"]),
                         "sv": pag["servidor"]})
        titulo = re.search(r"<title[^>]*>(.*?)</title>", pag["html"], re.S | re.I)
        if titulo:
            registro["t"] = analise.limpar(re.sub(r"<[^>]+>", " ", titulo.group(1)))[:90]
    selo = analise.parecido_com_autorizada(d, autorizadas)
    registro["r"] = selo["rotulo"]
    if selo.get("marca"):
        registro["m"] = selo["marca"]
    return registro


def _incorpora(reg, conhecidos):
    anterior = conhecidos.get(reg["d"], {})
    reg["pr"] = anterior.get("pr") or reg["visto"]
    reg["n_vivo"] = anterior.get("n_vivo", 0) + (1 if reg["st"] == "vivo" else 0)
    reg["n_obs"] = anterior.get("n_obs", 0) + 1
    if anterior.get("origem") == "certificado" and reg["origem"] == "indice":
        reg["origem"] = "indice+certificado"
    conhecidos[reg["d"]] = reg


def rodar(max_verificacoes=2000, workers=24, verbose=True, lote_salvar=250):
    t0 = time.time()
    autorizadas = fontes.lista_autorizadas()
    salvar_json(os.path.join(DATA, "autorizadas.json"), autorizadas)
    salvar_json(os.path.join(DOCS, "autorizadas.json"), autorizadas)
    if verbose:
        print("autorizadas: %d empresas, %d dominios (%.0fs)" % (
            autorizadas["total_empresas"], autorizadas["total_dominios"],
            time.time() - t0))

    estado_path = os.path.join(DATA, "estado.json")
    estado = ler_json(estado_path, {"dominios": {}, "varreduras": []})
    conhecidos = estado["dominios"]

    dominios = universo()
    fila_nome = candidatos(dominios, autorizadas)
    if verbose:
        print("universo: %d dominios, %d candidatos por nome (%.0fs)" % (
            len(dominios), len(fila_nome), time.time() - t0))

    recentes, erros_crt, referencia_ct = candidatos_por_certificado(autorizadas)
    if verbose:
        print("certificado: %d dominios, ref %s (%.0fs)" % (
            len(recentes), referencia_ct, time.time() - t0))

    fila = {}
    for c in recentes:
        fila[c["dominio"]] = c
    for c in fila_nome:
        fila.setdefault(c["dominio"], c)

    hoje_ts = time.mktime(time.strptime(time.strftime("%Y-%m-%d"), "%Y-%m-%d"))
    pendentes = []
    for d, c in fila.items():
        anterior = conhecidos.get(d)
        if anterior and anterior.get("visto"):
            idade = (hoje_ts - time.mktime(time.strptime(anterior["visto"], "%Y-%m-%d"))) / 86400
            if idade < 6:
                continue
        pendentes.append(c)
    pendentes.sort(key=lambda x: (-x["peso"], x["dominio"]))
    lote = pendentes[:max_verificacoes]
    if verbose:
        print("fila: %d pendentes, verificando %d (%.0fs)" % (
            len(pendentes), len(lote), time.time() - t0))

    resultados = []
    for i in range(0, len(lote), lote_salvar):
        pedaco = lote[i:i + lote_salvar]
        with ThreadPoolExecutor(max_workers=workers) as ex:
            for reg in ex.map(lambda item: verificar(item, autorizadas), pedaco):
                _incorpora(reg, conhecidos)
                resultados.append(reg)
        salvar_json(estado_path, estado)
        if verbose:
            print("  %d/%d verificados (%.0fs)" % (
                len(resultados), len(lote), time.time() - t0))

    todos = list(conhecidos.values())
    for r in todos:
        if r.get("st") == "vivo" and r.get("pb"):
            r["classe"] = ("clone" if r.get("r") == "clone_de_autorizada"
                           else "autorizada" if r.get("r") == "autorizada"
                           else "sem_registro")
        else:
            r["classe"] = "descartado"

    bets = [r for r in todos if r.get("classe") in ("clone", "sem_registro", "autorizada")]
    grupos = analise.clusters(bets, chaves=("ip", "k", "g"))
    operacoes = []
    for i, g in enumerate(sorted(grupos, key=len, reverse=True)):
        if len(g) < 2:
            for r in g:
                r["op"] = 0
            continue
        ident = i + 1
        ips = sorted({x for r in g for x in r.get("ip", [])})
        kits = sorted({r["k"] for r in g if r.get("k")})
        gas = sorted({x for r in g for x in r.get("g", [])})
        marcas = sorted({r.get("m", "") for r in g if r.get("m")})
        for r in g:
            r["op"] = ident
        operacoes.append({"id": ident, "n": len(g), "ips": ips[:6], "kits": kits[:4],
                          "ga": gas[:6], "marcas": marcas[:6], "n_ips": len(ips),
                          "hosts": [r["d"] for r in sorted(g, key=lambda z: -z.get("p", 0))][:12],
                          "clones": sum(1 for r in g if r.get("r") == "clone_de_autorizada")})

    vidas = []
    for r in todos:
        if (r.get("st") == "morto" and r.get("n_vivo", 0) >= 1 and r.get("pr")
                and r.get("visto") and r["pr"] < r["visto"]):
            try:
                a = time.mktime(time.strptime(r["pr"], "%Y-%m-%d"))
                b = time.mktime(time.strptime(r["visto"], "%Y-%m-%d"))
                vidas.append(max(1.0, (b - a) / 86400))
            except Exception:  # noqa: BLE001
                pass
    meia_vida = {"global": round(statistics.median(vidas), 1) if vidas else None,
                 "n": len(vidas)}
    por_kit = {}
    for r in todos:
        if (r.get("k") and r.get("st") == "morto" and r.get("n_vivo", 0) >= 1
                and r.get("pr") and r.get("visto") and r["pr"] < r["visto"]):
            try:
                a = time.mktime(time.strptime(r["pr"], "%Y-%m-%d"))
                b = time.mktime(time.strptime(r["visto"], "%Y-%m-%d"))
                por_kit.setdefault(r["k"], []).append(max(1.0, (b - a) / 86400))
            except Exception:  # noqa: BLE001
                pass
    meia_vida["por_kit"] = [{"kit": k, "dias": round(statistics.median(v), 1), "n": len(v)}
                            for k, v in sorted(por_kit.items(), key=lambda kv: -len(kv[1]))[:8]
                            if len(v) >= 2]

    mortos = [r for r in todos if r.get("st") == "morto"]
    vivos = [r for r in todos if r.get("st") == "vivo"]
    rotacao = []
    for novo in sorted(vivos, key=lambda r: r.get("pr", ""), reverse=True)[:600]:
        chaves_novo = set()
        if novo.get("k"):
            chaves_novo.add("k:" + novo["k"])
        for ip in novo.get("ip", []):
            if analise.ip_dedicado(ip):
                chaves_novo.add("ip:" + ip)
        for ga in novo.get("g", []):
            chaves_novo.add("g:" + ga)
        if not chaves_novo:
            continue
        for velho in mortos:
            if velho["d"] == novo["d"]:
                continue
            chaves_velho = set()
            if velho.get("k"):
                chaves_velho.add("k:" + velho["k"])
            for ip in velho.get("ip", []):
                if analise.ip_dedicado(ip):
                    chaves_velho.add("ip:" + ip)
            for ga in velho.get("g", []):
                chaves_velho.add("g:" + ga)
            comum = chaves_novo & chaves_velho
            if comum:
                rotacao.append({"novo": novo["d"], "morto": velho["d"],
                                "motivo": sorted(comum)[0].split(":")[0],
                                "desde": velho.get("visto", "")})
                break

    hoje = time.strftime("%Y-%m-%d")
    registro_dia = {
        "data": hoje, "universo": len(dominios),
        "candidatos": len(fila_nome), "certificados_dominios": len(recentes),
        "referencia_certificados": referencia_ct,
        "verificados_hoje": len(resultados),
        "novos_bets": sum(1 for r in resultados
                          if r.get("classe") in ("sem_registro", "clone", "autorizada")),
        "erros_certificado": erros_crt, "segundos": round(time.time() - t0),
    }
    estado["varreduras"].append(registro_dia)
    estado["varreduras"] = estado["varreduras"][-180:]
    salvar_json(estado_path, estado)
    salvar_json(os.path.join(DATA, "historico", hoje + ".json"), {
        "data": hoje, "dominios": resultados, "registro": registro_dia,
        "operacoes": operacoes[:60], "meia_vida": meia_vida, "rotacao": rotacao[:80]})

    for r in bets:
        r["br"] = analise.eh_brasil(r.get("d"), r.get("t", ""), r.get("s", []))
    todos_bets = sorted(bets, key=lambda r: (not r.get("br"),
                                             r.get("classe") == "autorizada",
                                             -r.get("p", 0), r.get("d", "")))
    por_tld = {}
    for r in todos_bets:
        tld = r["d"].rsplit(".", 1)[-1]
        por_tld[tld] = por_tld.get(tld, 0) + 1
    funil = {
        "universo": len(dominios), "candidatos_nome": len(fila_nome),
        "certificados_novos": len(recentes),
        "verificados": sum(1 for r in todos if r.get("visto")),
        "com_cara_de_bet": len(todos_bets),
        "sem_registro": sum(1 for r in todos_bets if r.get("classe") == "sem_registro"),
        "clones": sum(1 for r in todos_bets if r.get("classe") == "clone"),
        "autorizadas": sum(1 for r in todos_bets if r.get("classe") == "autorizada"),
        "no_brasil": sum(1 for r in todos_bets if r.get("br")),
        "operacoes": len(operacoes), "multi_dominio": sum(o["n"] for o in operacoes),
        "dominios_oficiais": autorizadas["total_dominios"],
        "empresas_oficiais": autorizadas["total_empresas"],
    }
    saida = {
        "gerado_em": hoje, "fonte_autorizadas": autorizadas["fonte"],
        "referencia_certificados": referencia_ct, "funil": funil,
        "dominios": todos_bets[:2500],
        "total_dominios": len(todos_bets),
        "descartados": sum(1 for r in todos if r.get("classe") == "descartado"),
        "operacoes": operacoes[:40], "meia_vida": meia_vida,
        "rotacao": rotacao[:40], "varreduras": estado["varreduras"][-60:],
        "por_tld": sorted(por_tld.items(), key=lambda kv: -kv[1])[:12],
        "termos": TERMOS_CRT, "erros_certificado": erros_crt,
    }
    salvar_json(os.path.join(DOCS, "atual.json"), saida)
    with open(os.path.join(DOCS, "dominios.csv"), "w", encoding="utf-8", newline="") as f:
        w = csv.writer(f)
        w.writerow(["dominio", "classe", "marca_autorizada", "pontos", "sinais",
                    "ips", "nameservers", "kit", "analytics", "primeira_aparição",
                    "visto", "status", "operacao", "brasil", "titulo"])
        for r in todos_bets:
            w.writerow([r.get("d"), r.get("classe"), r.get("m", ""), r.get("p"),
                        "; ".join(r.get("s", [])), " ".join(r.get("ip", [])),
                        " ".join(r.get("ns", [])), r.get("k", ""),
                        " ".join(r.get("g", [])), r.get("pr", ""), r.get("visto", ""),
                        r.get("st", ""), r.get("op", ""), "sim" if r.get("br") else "nao", r.get("t", "")])
    if verbose:
        print("funil: %s" % json.dumps(funil, ensure_ascii=False))
        print("tempo total: %.0fs" % (time.time() - t0))
    return saida

