"""Análise: sinais de casa de aposta, impressão digital do kit, IDs de
analytics, parecença com marca autorizada e clusters de infraestrutura."""
import hashlib
import ipaddress
import re
import unicodedata

# Termos fortes: sozinhos já indicam casa de aposta/jogo de azar.
FORTES = [
    r"tigrinhos?", r"fortune\s+(tiger|ox|mouse|rabbit|elephant)",
    r"aviator", r"cassino\s+online", r"casino\s+online", r"ca[çc]a[- ]n[íi]que(l|eis)",
    r"apostas?\s+esportivas?", r"jogos?\s+de\s+cassino", r"jogo\s+do\s+bicho",
    r"pgsoft", r"pragmatic\s+play", r"rodada\s+gr[áa]tis", r"giro\s+gr[áa]tis",
    r"tigre\s+da\s+sorte", r"b[ôo]nus\s+de\s+boas[- ]vindas", r"multiplicador",
    r"\bbetano\b", r"\bsportingbet\b", r"\bbet365\b", r"\bvaidebet\b",
    r"\bpixbet\b", r"\b1xbet\b", r"\bbetway\b", r"\bestrela\s*bet\b",
    r"\bblaze\b", r"\baviator\b", r"\bslots?\b",
]
# Termos médios: só contam acompanhados de termo forte.
MEDIOS = [
    r"apostas?", r"cassino", r"casino", r"roleta", r"jackpot", r"\bbingo\b",
    r"\bodds?\b", r"dep[óo]sito", r"saque\s+via\s+pix", r"\bpix\b",
    r"palpites?", r"placar", r"b[ôo]nus", r"torneio", r"afiliados?",
]
GENERICOS = {
    "cassino", "casino", "aposta", "apostas", "bet", "bets", "slot", "slots",
    "roleta", "bingo", "jogo", "jogos", "loteria", "esportiva", "esportivas",
    "palpite", "odds", "jackpot", "tigrinho", "sorte", "premios", "ganhe",
    "online", "oficial", "brasil", "brazil",
}
CDN = [ipaddress.ip_network(n) for n in (
    "104.16.0.0/12", "172.64.0.0/13", "162.158.0.0/15", "188.114.96.0/20",
    "173.245.48.0/20", "103.21.244.0/22", "108.162.192.0/18", "131.0.72.0/22",
    "141.101.64.0/18", "190.93.240.0/20", "197.234.240.0/22", "198.41.128.0/17",
    "35.184.0.0/13", "34.64.0.0/10", "52.0.0.0/8", "54.0.0.0/8", "18.0.0.0/8",
    "151.101.0.0/16", "199.232.0.0/16", "185.199.108.0/22",
)]
ANALYTICS = [
    (r"\bGTM-[A-Z0-9]{4,9}\b", "gtm"),
    (r"\bUA-\d{4,10}-\d{1,4}\b", "ga"),
    (r"\bG-[A-Z0-9]{7,12}\b", "ga4"),
    (r"\bAW-\d{6,12}\b", "ads"),
    (r"fbq\(\s*['\"]init['\"]\s*,\s*['\"](\d{9,20})", "pixel"),
    (r"\bym\(\s*(\d{6,12})", "yandex"),
]
ASSET = re.compile(r'(?:src|href)=["\']([^"\']+\.(?:js|css))(?:\?[^"\']*)?["\']', re.I)
FORTES_RE = [re.compile(p, re.I) for p in FORTES]
MEDIOS_RE = [re.compile(p, re.I) for p in MEDIOS]


def limpar(texto):
    return re.sub(r"\s+", " ", (texto or "")).strip()


def sinais_de_bet(html):
    """Pontua sinais de casa de aposta no HTML servido. Não executa JS."""
    texto = (html or "")[:400000]
    fortes, medios = [], []
    for p in FORTES_RE:
        m = p.search(texto)
        if m:
            fortes.append(m.group(0).lower()[:40])
    for p in MEDIOS_RE:
        m = p.search(texto)
        if m:
            medios.append(m.group(0).lower()[:40])
    fortes = sorted(set(fortes))
    medios = sorted(set(medios))
    pontos = 3 * len(fortes) + len(medios)
    return {"pontos": pontos, "fortes": fortes, "medios": medios,
            "sinais": (fortes + medios)[:12],
            "parece_bet": pontos >= 8 and len(fortes) >= 1}


def impressao_kit(html):
    """Hash dos arquivos estáticos + título normalizado.

    Dois domínios com o mesmo kit rodam o mesmo pacote, mesmo com marca
    diferente: é a assinatura da operação, mais estável que o domínio."""
    html = html or ""
    ativos = set()
    for m in ASSET.finditer(html):
        nome = m.group(1).split("?")[0].rstrip("/").rsplit("/", 1)[-1].lower()
        if nome and len(nome) < 80:
            ativos.add(nome)
    titulo = re.search(r"<title[^>]*>(.*?)</title>", html, re.S | re.I)
    titulo = limpar(re.sub(r"<[^>]+>", " ", titulo.group(1))) if titulo else ""
    titulo = re.sub(r"\d+", "#", titulo.lower())[:80]
    if not ativos and not titulo:
        return ""
    chave = "|".join(sorted(ativos)) + "||" + titulo
    return hashlib.sha1(chave.encode("utf-8")).hexdigest()[:12]


def ids_analytics(html):
    html = html or ""
    ids = []
    for padrao, tipo in ANALYTICS:
        for m in re.finditer(padrao, html, re.I):
            valor = (m.group(1) if m.groups() else m.group(0)).strip()
            if tipo == "pixel":
                valor = "fbq:" + valor
            if valor and valor not in ids:
                ids.append(valor)
    return ids[:8]


def normalizar(texto):
    s = unicodedata.normalize("NFKD", (texto or "").lower())
    s = "".join(c for c in s if not unicodedata.combining(c))
    return re.sub(r"[^a-z0-9]", "", s)


def levenshtein(a, b):
    if a == b:
        return 0
    if not a or not b:
        return max(len(a), len(b))
    antes = list(range(len(b) + 1))
    for i, ca in enumerate(a, 1):
        atual = [i]
        for j, cb in enumerate(b, 1):
            atual.append(min(antes[j] + 1, atual[j - 1] + 1,
                             antes[j - 1] + (ca != cb)))
        antes = atual
    return antes[-1]


SUFIXO2 = {"com", "net", "org", "bet", "app", "dev", "art", "blog", "inf",
           "adv", "eng", "med", "seg", "emp", "eco", "pro", "srv", "tv",
           "co", "com", "edu", "gov"}


def sld(dominio):
    partes = (dominio or "").lower().split(".")
    if len(partes) >= 3 and partes[-2] in SUFIXO2:
        return partes[-3]
    return partes[0] if partes else ""


def _marcas(autorizadas):
    saida = {}
    for e in autorizadas.get("empresas", []):
        for m in e["marcas"]:
            n = normalizar(m)
            if len(n) >= 6 and n not in GENERICOS:
                saida.setdefault(n, m)
        for d in e["dominios"]:
            n = normalizar(sld(d))
            if len(n) >= 6 and n not in GENERICOS:
                saida.setdefault(n, m or sld(d))
    return saida


RESTOS_OK = {"br", "oficial", "bet", "bets", "online", "vip", "jogos",
             "apostas", "site", "app", "com", "net"}


def parecido_com_autorizada(dominio, autorizadas):
    """Selo: autorizada, clone de autorizada (nome muito parecido) ou sem registro."""
    d = (dominio or "").lower()
    oficiais = {x.lower().strip(".") for e in autorizadas.get("empresas", [])
                for x in e["dominios"]}
    if d in oficiais:
        return {"rotulo": "autorizada",
                "motivo": "domínio consta na lista oficial do SPA/MF", "marca": ""}
    alvo = normalizar(sld(d))
    if len(alvo) < 6:
        return {"rotulo": "sem_registro",
                "motivo": "domínio fora da lista oficial do SPA/MF", "marca": ""}
    marcas = _marcas(autorizadas)
    if alvo in marcas:
        # marca idêntica, domínio diferente do oficial
        return {"rotulo": "clone_de_autorizada",
                "motivo": "usa exatamente a marca %s, mas em domínio que não é o oficial"
                          % marcas[alvo], "marca": marcas[alvo]}
    melhor, dist = "", 99
    for n in marcas:
        if abs(len(n) - len(alvo)) > 3:
            continue
        if n in alvo:
            resto = alvo.replace(n, "", 1)
            if resto in RESTOS_OK or resto.isdigit():
                return {"rotulo": "clone_de_autorizada",
                        "motivo": "marca %s com sufixo no domínio" % marcas[n],
                        "marca": marcas[n]}
        dv = levenshtein(alvo, n)
        if dv <= 1 and dv < dist:
            melhor, dist = n, dv
    if melhor and dist <= 1:
        return {"rotulo": "clone_de_autorizada",
                "motivo": "nome a 1 caractere da marca autorizada %s" % marcas[melhor],
                "marca": marcas[melhor]}
    return {"rotulo": "sem_registro",
            "motivo": "domínio fora da lista oficial do SPA/MF", "marca": ""}


def ip_dedicado(ip):
    try:
        end = ipaddress.ip_address(ip)
    except Exception:  # noqa: BLE001
        return False
    return not any(end in rede for rede in CDN)


def clusters(itens, chaves=("ip", "k", "g", "ns")):
    """Componentes conexos por infraestrutura compartilhada (union-find).

    IP de CDN não conta: milhares de sites dividem o mesmo endereço."""
    pai = {}

    def acha(x):
        pai.setdefault(x, x)
        while pai[x] != x:
            pai[x] = pai[pai[x]]
            x = pai[x]
        return x

    def une(a, b):
        ra, rb = acha(a), acha(b)
        if ra != rb:
            pai[rb] = ra

    for i, it in enumerate(itens):
        no = "d:%d" % i
        acha(no)
        for chave in chaves:
            valores = it.get(chave) or []
            if isinstance(valores, str):
                valores = [valores]
            for v in valores:
                if not v:
                    continue
                if chave == "ip" and not ip_dedicado(v):
                    continue
                une(no, "%s:%s" % (chave, str(v).lower()))
    grupos = {}
    for i, it in enumerate(itens):
        grupos.setdefault(acha("d:%d" % i), []).append(it)
    return list(grupos.values())
