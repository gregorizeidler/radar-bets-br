"""Fontes públicas: lista oficial de bets autorizadas (SPA/MF), Certificate
Transparency (crt.sh) e DNS-over-HTTPS. Somente leitura, sem login, sem cadastro."""
import json
import re
import html as htmlmod
import time
import urllib.parse
import urllib.request

UA = ("Mozilla/5.0 (compatible; RadarBetsBR/1.0; "
      "+https://github.com/gregorizeidler/radar-bets-br)")

SPA_URL = ("https://www.gov.br/fazenda/pt-br/composicao/orgaos/"
           "secretaria-de-premios-e-apostas/transparencia-ativa-processos-de-"
           "autorizacao-de-apostas-de-quota-fixa/empresas-autorizadas")

TERMOS = ["%.bet", "%.tigrinho", "%.cassino", "%.fortune", "%.aviator",
          "%.aposta", "%.roleta", "%.slot"]
RESGATE = {"bet.br", "com.br", "net.br", "org.br", "app.br", "dev.br",
           "art.br", "blog.br", "inf.br", "adv.br", "eng.br", "med.br",
           "seg.br", "emp.br", "eco.br", "pro.br", "srv.br", "tv.br",
           "co.uk", "com.ar", "com.ve", "co.mz", "com.py"}


def baixar(url, timeout=30, tentativas=3, headers=None, max_bytes=2000000):
    """GET com prazo total e teto de bytes: servidor que pinga devagar não trava a fila."""
    h = {"User-Agent": UA, "Accept": "*/*",
         "Accept-Language": "pt-BR,pt;q=0.9"}
    if headers:
        h.update(headers)
    ultimo = None
    for i in range(tentativas):
        try:
            req = urllib.request.Request(url, headers=h)
            with urllib.request.urlopen(req, timeout=timeout) as r:
                inicio = time.time()
                partes, total = [], 0
                while True:
                    pedaco = r.read(65536)
                    if not pedaco:
                        break
                    partes.append(pedaco)
                    total += len(pedaco)
                    if total >= max_bytes or time.time() - inicio > timeout:
                        break
                return b"".join(partes), dict(r.headers), getattr(r, "status", 200)
        except Exception as e:  # noqa: BLE001
            ultimo = e
            time.sleep(1.2 * (i + 1))
    raise ultimo


def _txt(celula):
    s = re.sub(r"<[^>]+>", " ", celula)
    s = htmlmod.unescape(s)
    return re.sub(r"\s+", " ", s).strip()


def dominio_base(host):
    host = host.strip().lower().strip(".")
    if host.startswith("*."):
        host = host[2:]
    if not host:
        return host
    partes = host.split(".")
    if len(partes) < 2:
        return host
    if ".".join(partes[-2:]) in RESGATE:
        return ".".join(partes[-3:])
    return ".".join(partes[-2:])


def lista_autorizadas():
    """Lê a tabela oficial: empresa, CNPJ, marcas, domínios, portaria, processo."""
    bruto, _, _ = baixar(SPA_URL, timeout=60, tentativas=3)
    pagina = bruto.decode("utf-8", "ignore")
    m = re.search(r"<table.*?</table>", pagina, re.S)
    if not m:
        raise RuntimeError("tabela de autorizadas não encontrada na página do SPA")
    tabela = m.group(0)
    empresas = []
    for linha in re.findall(r"<tr[^>]*>(.*?)</tr>", tabela, re.S)[1:]:
        celulas = re.findall(r"<t[dh][^>]*>(.*?)</t[dh]>", linha, re.S)
        if len(celulas) < 5:
            continue
        empresa = _txt(celulas[1])
        cnpj = _txt(celulas[2])
        if not re.search(r"\d{2}\.\d{3}\.\d{3}/\d{4}-\d{2}", cnpj):
            continue
        marcas = [x.strip(" •").strip() for x in re.split(r"•", _txt(celulas[3]))]
        marcas = [x for x in marcas if x]
        dominios = [d.lower().strip(",;") for d in _txt(celulas[4]).split()
                    if "." in d]
        portaria = _txt(celulas[5]) if len(celulas) > 5 else ""
        req = _txt(celulas[6]) if len(celulas) > 6 else ""
        pdfs = re.findall(r'href="([^"]+\.pdf)"', linha)
        empresas.append({"empresa": empresa, "cnpj": cnpj, "marcas": marcas,
                         "dominios": dominios, "portaria": portaria,
                         "requerimento": req, "processos": pdfs})
    if not empresas:
        raise RuntimeError("nenhuma empresa parseada da lista oficial")
    return {
        "fonte": SPA_URL,
        "atualizado_em": time.strftime("%Y-%m-%d"),
        "total_empresas": len(empresas),
        "total_dominios": sum(len(e["dominios"]) for e in empresas),
        "total_marcas": sum(len(e["marcas"]) for e in empresas),
        "empresas": empresas,
    }


def certificados(termo, dias=4, timeout=90):
    """Certificados emitidos na janela, cujo nome contém o termo."""
    url = "https://crt.sh/?q=%s&output=json" % urllib.parse.quote(termo)
    bruto, _, _ = baixar(url, timeout=timeout, tentativas=2)
    try:
        registros = json.loads(bruto.decode("utf-8", "ignore"))
    except Exception:  # noqa: BLE001
        return []
    if not isinstance(registros, list):
        return []
    corte = time.time() - dias * 86400
    agulha = termo.replace("%.", "").lower()
    saida = []
    for r in registros:
        try:
            emissao = time.mktime(time.strptime(
                r.get("not_before", "")[:19], "%Y-%m-%dT%H:%M:%S"))
        except Exception:  # noqa: BLE001
            continue
        if emissao < corte:
            continue
        for nome in str(r.get("name_value", "")).split("\n"):
            nome = nome.strip().lower().lstrip("*.")
            if not nome or " " in nome or agulha not in nome:
                continue
            saida.append({
                "nome": nome,
                "dominio": dominio_base(nome),
                "emissao": r.get("not_before", "")[:10],
                "emissor": (r.get("issuer_name") or "")[:120],
                "certificado": r.get("id"),
            })
    return saida


def _resolve(host):
    import socket
    return socket.getaddrinfo(host, None, socket.AF_INET, socket.SOCK_STREAM)


def dns(host, timeout=3):
    """Resolve pelo resolver do sistema com prazo: DNS travado não segura a fila."""
    import concurrent.futures as cf
    saida = {"a": [], "ns": []}
    try:
        with cf.ThreadPoolExecutor(max_workers=1) as ex:
            for info in ex.submit(_resolve, host).result(timeout=timeout):
                ip = info[4][0]
                if ip not in saida["a"] and re.match(r"^\d{1,3}(\.\d{1,3}){3}$", ip):
                    saida["a"].append(ip)
    except Exception:  # noqa: BLE001
        pass
    return saida


def pagina(host, timeout=6):
    """Um único GET na home, sem seguir caminhos internos, sem login."""
    for esquema in ("https", "http"):
        try:
            bruto, headers, status = baixar(
                "%s://%s/" % (esquema, host), timeout=timeout, tentativas=1)
            return {
                "status": status,
                "servidor": (headers.get("Server") or "")[:60],
                "tamanho": len(bruto),
                "html": bruto[:400000].decode("utf-8", "ignore"),
                "url": "%s://%s/" % (esquema, host),
            }
        except Exception:  # noqa: BLE001
            continue
    return None
