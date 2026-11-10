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


VOCAB_BUNDLE = [
    "cassino", "casino", "aposta", "apostas", "aviator", "pragmatic", "pgsoft",
    "slot", "slots", "odds", "bonus", "bônus", "giro", "rodada", "multiplicador",
    "deposito", "depósito", "saque", "pix", "fortune tiger", "tigrinho", "roleta",
    "jackpot", "crash", "cassino online", "casino online", "apuestas",
]


def evidencia_bundle(texto):
    """Quanto de vocabulário de aposta existe no bundle, contando repetição.

    Um bundle de e-commerce cita "bonus" uma vez; o de uma casa de aposta cita
    cassino, slot, odds e rodada dezenas de vezes. Por isso a frequência entra.
    """
    low = (texto or "").lower()
    if not low:
        return {"pontos": 0, "termos": [], "forte": False}
    achados = []
    total = 0
    for termo in VOCAB_BUNDLE:
        n = low.count(termo)
        if n:
            total += min(n, 10)
            if n >= 3:
                achados.append("%s x%d" % (termo, n))
    forte = any(p.search(low) for p in FORTES_RE)
    return {"pontos": total if forte else 0, "termos": achados[:8], "forte": forte}


def sinais_de_texto(texto):
    """Igual a sinais_de_bet, mas sem cortar o texto (usado no bundle)."""
    texto = texto or ""
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


def clusters(itens, max_por_ip=4):
    """Componentes conexos: kit, ID de analytics e IP dedicado.

    Kit (arquivos estáticos + título) e ID de analytics são a impressão digital
    de quem monta o site. IP só vale quando poucos domínios o dividem — acima
    disso é hospedagem/CDN e não diz nada."""
    pai = {i: i for i in range(len(itens))}

    def acha(x):
        while pai[x] != x:
            pai[x] = pai[pai[x]]
            x = pai[x]
        return x

    def une(a, b):
        ra, rb = acha(a), acha(b)
        if ra != rb:
            pai[rb] = ra

    chaves = {}
    ips_usados = {}
    for i, r in enumerate(itens):
        if r.get("k"):
            chaves.setdefault("k:" + r["k"], []).append(i)
        for ga in r.get("g", []):
            chaves.setdefault("g:" + ga, []).append(i)
        for ip in r.get("ip", []):
            ips_usados.setdefault(ip, []).append(i)
    for ip, donos in ips_usados.items():
        if len(donos) <= max_por_ip and ip_dedicado(ip):
            chaves.setdefault("ip:" + ip, donos)
    for donos in chaves.values():
        for j in donos[1:]:
            une(donos[0], j)

    grupos = {}
    for i in range(len(itens)):
        grupos.setdefault(acha(i), []).append(itens[i])
    return list(grupos.values())

SINAIS_BR = ["pix", "r$", "reais", "cpf", "brasil", "brl", "jogo do bicho",
             "tigrinho", "saque", "aposta", "apostas", "cassino", "placar",
             "rodada gratis", "rodada grátis", "depósito", "deposito"]


def eh_brasil(dominio, titulo="", sinais=None):
    """Marca o domínio como falando com o brasileiro.

    Não é nacionalidade de empresa: é sinal de Pix, reais, CPF, pt-BR ou .br."""
    d = (dominio or "").lower()
    pontos = 0
    if d.endswith(".br"):
        pontos += 4
    texto = ((titulo or "") + " " + " ".join(sinais or [])).lower()
    for s in SINAIS_BR:
        if s in texto:
            pontos += 2
    return pontos >= 4

def sinais_no_pacote(html, base_url=""):
    """Sinais dentro dos arquivos .js da home.

    Site que monta a tela por JavaScript serve uma casca vazia: o texto de
    aposta está no bundle, não no HTML. Aqui a gente pontua o bundle com a
    mesma régua, mas com corte mais alto, porque biblioteca de terceiro pode
    citar "casino" de passagem.
    """
    import urllib.parse
    urls = []
    for m in ASSET.finditer(html or ""):
        u = m.group(1)
        if not u.lower().split("?")[0].endswith(".js"):
            continue
        urls.append(urllib.parse.urljoin(base_url or "", u))
    return urls[:3]

