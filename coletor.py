"""Radar de bets: pipeline diário.

Fontes, todas públicas e sem chave:
  1. Lista oficial de operadoras autorizadas (SPA/Ministério da Fazenda).
  2. Certificate Transparency (crt.sh): domínios com certificado novo.
  3. Tranco: universo de domínios vivos (top 1 milhão).

O que o coletor faz com cada candidato: resolve DNS, faz UM GET na home
(sem login, sem cadastro, sem tocar em página de depósito), mede os sinais
de casa de aposta, calcula a impressão digital do kit (arquivos estáticos +
título), extrai IDs de analytics e compara o nome com as marcas autorizadas.
"""
import csv
import json
import os
import re
import statistics
import time
import zipfile
import io
from concurrent.futures import ThreadPoolExecutor

import fontes
import analise

RAIZ = os.path.dirname(os.path.abspath(__file__))
DATA = os.path.join(RAIZ, "data")
DOCS = os.path.join(RAIZ, "docs", "dados")

TERMOS_CRT = ["%.bet.br", "%.bet", "%.tigrinho", "%.cassino", "%.fortune",
              "%.aviator", "%.aposta", "%.slot", "%.blaze"]

# nome de domínio com cara de aposta (só pré-filtro; a confirmação é a página)
PADRAO_NOME = re.compile(
    r"(^|[.\-])(bet|bets|bet\d{1,4}|betano|bet365|sportingbet|vaidebet|pixbet|"
    r"aposta|apostas|apostaganha|cassino|casino|tigrinho|tigre|aviator|blaze|"
    r"roleta|bingo|slots?|jackpot|loteria|esportiva|palpite|odds)([.\-]|$)",
    re.I)

# termos que indicam aposta no próprio nome, para ordenar a fila
PESO_NOME = {"tigrinho": 6, "aviator": 6, "fortune tiger": 6, "blaze": 5,
             "cassino": 4, "casino": 4, "aposta": 4, "apostas": 4,
             "roleta": 3, "slot": 3, "bingo": 3, "jackpot": 3, "bet": 2}

EXCLUIR_HOSTS = {"bethesda.net", "betterhelp.com", "forebet.com"}


def _caminho(*p):
    c = os.path.join(*p)
    os.makedirs(os.path.dirname(c), exist_ok=True)
    return c


def ler_json(caminho, padrao=None):
    try:
        with open(caminho, encoding="utf-8") as f:
            return json.load(f)
    except Exception:  # noqa: BLE001
        return padrao


def salvar_json(caminho, dados):
    os.makedirs(os.path.dirname(caminho), exist_ok=True)
    with open(caminho, "w", encoding="utf-8") as f:
        json.dump(dados, f, ensure_ascii=False, separators=(",", ":"))
        f.write("\n")


def tranco(dias_cache=7):
    """Universo de domínios vivos. Cache local de uma semana."""
    csv_path = os.path.join(DATA, "tranco.csv")
    if os.path.exists(csv_path) and time.time() - os.path.getmtime(csv_path) < dias_cache * 86400:
        with open(csv_path, encoding="utf-8") as f:
            return [l.split(",", 1)[1].strip() for l in f if "," in l]
    bruto, _, _ = fontes.baixar("https://tranco-list.eu/top-1m.csv.zip", timeout=120)
    with zipfile.ZipFile(io.BytesIO(bruto)) as z:
        nome = [n for n in z.namelist() if n.endswith(".csv")][0]
        texto = z.read(nome).decode("utf-8", "ignore")
    os.makedirs(DATA, exist_ok=True)
    with open(csv_path, "w", encoding="utf-8") as f:
        f.write(texto)
    return [l.split(",", 1)[1].strip() for l in texto.splitlines() if "," in l]


def peso_nome(dominio):
    base = analise.sld(dominio)
    ponto = 0
    for termo, peso in PESO_NOME.items():
        if termo in base:
            ponto = max(ponto, peso)
    if dominio.endswith(".bet"):
        ponto += 3
    if base.startswith(("bet", "aposta", "cassino", "tigrinho", "blaze")):
        ponto += 2
    return ponto


def candidatos_por_nome(dominios, autorizadas):
    oficiais = {d.lower() for e in autorizadas["empresas"] for d in e["dominios"]}
    fila = []
    for d in dominios:
        d = d.lower().strip()
        if not d or d in EXCLUIR_HOSTS or d in oficiais:
            continue
        if d.endswith((".gov.br", ".edu.br", ".gov", ".mil.br")):
            continue
        alvo = analise.sld(d)
        if not PADRAO_NOME.search(d) and not PADRAO_NOME.search(alvo):
            continue
        fila.append({"dominio": d, "peso": peso_nome(d), "origem": "tranco"})
    fila.sort(key=lambda x: (-x["peso"], x["dominio"]))
    return fila


def candidatos_por_certificado(autorizadas, dias=45):
    """Domínios com certificado novo. A janela é relativa ao certificado mais
    recente visto, para não depender do relógio da máquina."""
    oficiais = {d.lower() for e in autorizadas["empresas"] for d in e["dominios"]}
    vistos = {}
    erros = []
    def um(termo):
        try:
            return termo, fontes.certificados(termo, dias=100000)
        except Exception as e:  # noqa: BLE001
            return termo, e
    with ThreadPoolExecutor(max_workers=3) as ex:
        for termo, res in ex.map(um, TERMOS_CRT):
            if isinstance(res, Exception):
                erros.append({"termo": termo, "erro": str(res)[:120]})
                continue
            for c in res:
                vistos.setdefault(c["dominio"], c["emissao"])
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
        if ts >= corte and (PADRAO_NOME.search(d) or d.endswith(".bet.br")):
            recentes.append({"dominio": d, "peso": peso_nome(d) + 2,
                             "origem": "certificado", "emissao": emissao})
    recentes.sort(key=lambda x: (-x["peso"], x["dominio"]))
    return recentes, erros, referencia


def verificar(item, autorizadas, timeout=9):
    d = item["dominio"]
    info = fontes.dns(d, timeout=6)
    pag = fontes.pagina(d, timeout=timeout)
    registro = {
        "d": d,
        "origem": item.get("origem", ""),
        "ip": info["a"][:4],
        "ns": [n.lower() for n in info["ns"][:4]],
        "visto": time.strftime("%Y-%m-%d"),
        "st": "morto",
        "p": 0,
        "s": [],
        "k": "",
        "g": [],
        "t": "",
        "sv": "",
        "ht": 0,
    }
    if pag:
        sinais = analise.sinais_de_bet(pag["html"])
        registro.update({
            "st": "vivo",
            "ht": pag["status"],
            "p": sinais["pontos"],
            "pf": sinais["fortes"][:6],
            "pb": sinais["parece_bet"],
            "s": sinais["sinais"],
            "k": analise.impressao_kit(pag["html"]),
            "g": analise.ids_analytics(pag["html"]),
            "sv": pag["servidor"],
        })
        titulo = re.search(r"<title[^>]*>(.*?)</title>", pag["html"], re.S | re.I)
        if titulo:
            registro["t"] = analise.limpar(re.sub(r"<[^>]+>", " ", titulo.group(1)))[:90]
    selo = analise.parecido_com_autorizada(d, autorizadas)
    registro["r"] = selo["rotulo"]
    if selo.get("marca"):
        registro["m"] = selo["marca"]
    return registro


def rodar(max_verificacoes=260, workers=14, verbose=True):
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

    universo = tranco()
    por_nome = candidatos_por_nome(universo, autorizadas)
    if verbose:
        print("tranco: %d dominios, %d candidatos por nome (%.0fs)" % (
            len(universo), len(por_nome), time.time() - t0))

    recentes, erros_crt, referencia_ct = candidatos_por_certificado(autorizadas)
    if verbose:
        print("certificado: %d dominios novos, ref %s, erros %d (%.0fs)" % (
            len(recentes), referencia_ct, len(erros_crt), time.time() - t0))

    fila = {c["dominio"]: c for c in recentes or []}
    for c in por_nome:
        fila.setdefault(c["dominio"], c)
    # prioridade: certificado novo primeiro, depois nome mais forte,
    # e por último o que nunca foi verificado ou está velho
    pendentes = []
    for d, c in fila.items():
        anterior = conhecidos.get(d)
        if anterior and anterior.get("visto"):
            idade = (time.mktime(time.strptime(time.strftime("%Y-%m-%d"), "%Y-%m-%d"))
                     - time.mktime(time.strptime(anterior["visto"], "%Y-%m-%d"))) / 86400
            if idade < 6:
                continue
        pendentes.append(c)
    pendentes.sort(key=lambda x: (-x["peso"], x["dominio"]))
    lote = pendentes[:max_verificacoes]
    if verbose:
        print("fila: %d pendentes, verificando %d (%.0fs)" % (
            len(pendentes), len(lote), time.time() - t0))

    resultados = []
    if lote:
        with ThreadPoolExecutor(max_workers=workers) as ex:
            for reg in ex.map(lambda i: verificar(i, autorizadas), lote):
                resultados.append(reg)
                anterior = conhecidos.get(reg["d"], {})
                reg["pr"] = anterior.get("pr") or reg["visto"]
                reg["n_vivo"] = anterior.get("n_vivo", 0) + (1 if reg["st"] == "vivo" else 0)
                reg["n_obs"] = anterior.get("n_obs", 0) + 1
                conhecidos[reg["d"]] = reg
    if verbose:
        print("verificados: %d (%.0fs)" % (len(resultados), time.time() - t0))

    # ------- análise sobre o histórico inteiro -------
    todos = list(conhecidos.values())
    for r in todos:
        if r.get("st") == "vivo" and r.get("pb"):
            r["classe"] = ("clone" if r.get("r") == "clone_de_autorizada"
                           else "autorizada" if r.get("r") == "autorizada"
                           else "sem_registro")
        else:
            r["classe"] = "descartado"

    bets = [r for r in todos if r.get("classe") in ("clone", "sem_registro", "autorizada")]

    grupos = analise.clusters(bets, chaves=("ip", "k", "g", "ns"))
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
        operacoes.append({
            "id": ident, "n": len(g), "ips": ips[:6], "kits": kits[:4],
            "ga": gas[:6], "marcas": marcas[:6],
            "hosts": [r["d"] for r in sorted(g, key=lambda z: -z.get("p", 0))][:12],
            "n_ips": len(ips), "clones": sum(1 for r in g if r.get("r") == "clone_de_autorizada"),
        })

    # meia-vida: dias entre a primeira aparição e o momento em que sumiu
    vidas = []
    for r in todos:
        if (r.get("st") == "morto" and r.get("n_vivo", 0) >= 1
                and r.get("pr") and r.get("visto") and r["pr"] < r["visto"]):
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
    meia_vida["por_kit"] = [
        {"kit": k, "dias": round(statistics.median(v), 1), "n": len(v)}
        for k, v in sorted(por_kit.items(), key=lambda kv: -len(kv[1]))[:8]
        if len(v) >= 2]

    # rotação: domínio novo que herda infraestrutura de um domínio morto
    mortos = [r for r in todos if r.get("st") == "morto"]
    vivos = [r for r in todos if r.get("st") == "vivo"]
    rotacao = []
    for novo in sorted(vivos, key=lambda r: r.get("pr", ""), reverse=True)[:400]:
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
        "data": hoje,
        "certificados_dominios": len(recentes),
        "referencia_certificados": referencia_ct,
        "universo_tranco": len(universo),
        "candidatos_por_nome": len(por_nome),
        "verificados_hoje": len(resultados),
        "parecem_bet": sum(1 for r in resultados if r.get("classe") in (
            "sem_registro", "clone", "autorizada")),
        "erros_certificado": erros_crt,
        "segundos": round(time.time() - t0),
    }
    estado["varreduras"].append(registro_dia)
    estado["varreduras"] = estado["varreduras"][-180:]
    salvar_json(estado_path, estado)

    salvar_json(os.path.join(DATA, "historico", hoje + ".json"), {
        "data": hoje, "dominios": resultados, "registro": registro_dia,
        "operacoes": operacoes[:60], "meia_vida": meia_vida,
        "rotacao": rotacao[:80],
    })

    # ------- saída do site -------
    todos_bets = [r for r in todos if r.get("classe") in ("sem_registro", "clone", "autorizada")]
    todos_bets.sort(key=lambda r: (r.get("classe") == "autorizada",
                                   -r.get("p", 0), r.get("d", "")))
    funil = {
        "universo": len(universo),
        "candidatos_nome": len(por_nome),
        "certificados_novos": len(recentes),
        "verificados": sum(1 for r in todos if r.get("visto")),
        "com_cara_de_bet": len(todos_bets),
        "sem_registro": sum(1 for r in todos_bets if r.get("classe") == "sem_registro"),
        "clones": sum(1 for r in todos_bets if r.get("classe") == "clone"),
        "autorizadas": sum(1 for r in todos_bets if r.get("classe") == "autorizada"),
        "operacoes": len(operacoes),
        "multi_dominio": sum(o["n"] for o in operacoes),
        "dominios_oficiais": autorizadas["total_dominios"],
        "empresas_oficiais": autorizadas["total_empresas"],
    }
    saida = {
        "gerado_em": hoje,
        "fonte_autorizadas": autorizadas["fonte"],
        "referencia_certificados": referencia_ct,
        "funil": funil,
        "dominios": todos_bets,
        "descartados": sum(1 for r in todos if r.get("classe") == "descartado"),
        "operacoes": operacoes[:40],
        "meia_vida": meia_vida,
        "rotacao": rotacao[:40],
        "varreduras": estado["varreduras"][-30:],
        "termos": TERMOS_CRT,
        "erros_certificado": erros_crt,
    }
    salvar_json(os.path.join(DOCS, "atual.json"), saida)
    with open(os.path.join(DOCS, "dominios.csv"), "w", encoding="utf-8", newline="") as f:
        w = csv.writer(f)
        w.writerow(["dominio", "classe", "marca_autorizada", "pontos",
                    "sinais", "ips", "nameservers", "kit", "analytics",
                    "primeira_aparição", "visto", "status", "operacao", "titulo"])
        for r in todos_bets:
            w.writerow([r.get("d"), r.get("classe"), r.get("m", ""), r.get("p"),
                        "; ".join(r.get("s", [])), " ".join(r.get("ip", [])),
                        " ".join(r.get("ns", [])), r.get("k", ""),
                        " ".join(r.get("g", [])), r.get("pr", ""), r.get("visto", ""),
                        r.get("st", ""), r.get("op", ""), r.get("t", "")])
    if verbose:
        print("funil: %s" % json.dumps(funil, ensure_ascii=False))
        print("tempo total: %.0fs" % (time.time() - t0))
    return saida
