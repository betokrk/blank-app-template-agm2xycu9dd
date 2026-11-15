#!/usr/bin/env python3
"""Notícias da ABCCC dentro do portal (sem RSS — a ABCCC não publica feed).

Por que não RSS: o site oficial (cavalocrioulo.org.br) responde HTML em
/feed/, /rss, /rss.xml e /noticias/feed/. Não existe feed para assinar.

O que este módulo faz:
  - lê a página pública de notícias da ABCCC e extrai título, data, resumo
    e link de cada item;
  - lê a MATÉRIA INTEIRA de cada notícia, para ser mostrada dentro do
    portal, sem mandar o visitante para fora;
  - guarda em cache (lista: 3 h, matéria: 6 h) para não bater no site da
    Associação a cada visita;
  - se a ABCCC estiver fora do ar, devolve o último resultado bom (nunca
    inventa notícia nem mostra lista vazia por falha momentânea).

O conteúdo é sempre da ABCCC: a tela mostra autor, data e o link da fonte
original em toda matéria.
"""
import re
import json
import time
import html as htmlmod
import urllib.request

URL_NOTICIAS = "https://www.cavalocrioulo.org.br/noticias"
BASE = "https://www.cavalocrioulo.org.br"
UA = ("Mozilla/5.0 (compatible; PortalFreioProprietario/1.0; "
      "+https://proprietario.net)")
CACHE_SEGUNDOS = 60 * 60 * 3        # 3 horas

MESES = {
    "JANEIRO": 1, "FEVEREIRO": 2, "MARCO": 3, "ABRIL": 4, "MAIO": 5, "JUNHO": 6,
    "JULHO": 7, "AGOSTO": 8, "SETEMBRO": 9, "OUTUBRO": 10, "NOVEMBRO": 11,
    "DEZEMBRO": 12,
}

_cache = {"quando": 0, "itens": [], "erro": None}


def _sem_acento(s):
    tabela = str.maketrans(
        "ÁÀÃÂÉÊÍÓÔÕÚÇáàãâéêíóôõúç",
        "AAAAEEIOOOUCaaaaeeiooouc")
    return s.translate(tabela)


def _limpa(s):
    s = re.sub(r"<script[\s\S]*?</script>", " ", s)
    s = re.sub(r"<style[\s\S]*?</style>", " ", s)
    s = re.sub(r"<[^>]+>", " ", s)
    s = htmlmod.unescape(s).replace("\xa0", " ")
    return re.sub(r"\s+", " ", s).strip()


def _data_extenso(texto):
    t = _sem_acento(texto.upper())
    m = re.search(r"(\d{1,2})\s+DE\s+([A-Z]+)\s+DE\s+(\d{4})", t)
    if not m:
        return None
    mes = MESES.get(m.group(2))
    return f"{m.group(3)}-{mes:02d}-{int(m.group(1)):02d}" if mes else None


def _data_numerica(texto):
    m = re.search(r"(\d{1,2})/(\d{1,2})/(\d{4})", texto)
    if not m:
        return None
    dia, mes, ano = m.groups()
    return f"{ano}-{int(mes):02d}-{int(dia):02d}"


def _baixar(url=URL_NOTICIAS):
    req = urllib.request.Request(url, headers={"User-Agent": UA})
    with urllib.request.urlopen(req, timeout=20) as r:
        return r.read().decode("utf-8", errors="replace")


def extrair_noticias(pagina):
    """Devolve a lista de notícias da página, da mais nova para a mais velha."""
    itens, ordem = {}, []

    def guardar(nid, titulo, url, data, resumo=""):
        if not (nid and titulo and data):
            return
        titulo = htmlmod.unescape(_limpa(titulo))
        if len(titulo) < 15:
            return
        if nid not in itens:
            ordem.append(nid)
            itens[nid] = {
                "id": nid, "titulo": titulo,
                "url": url if url.startswith("http") else BASE + url,
                "data": data,
                "resumo": htmlmod.unescape(_limpa(resumo))[:400],
            }
        elif not itens[nid]["resumo"] and resumo:
            itens[nid]["resumo"] = htmlmod.unescape(_limpa(resumo))[:400]

    # destaque do topo (manchete)
    for m in re.finditer(
            r'<h2[^>]*>\s*<a\s+href="([^"]*detalhes/(\d+)/[^"]*)"\s+title="([^"]*)"[^>]*>',
            pagina):
        url, nid, titulo = m.group(1), m.group(2), m.group(3)
        trecho = pagina[m.end():m.end() + 4000]
        d = re.search(r"data-detalhe[\s\S]{0,200}?(\d{1,2}\s+DE\s+[A-Za-zÀ-ÿ]+\s+DE\s+\d{4})", trecho)
        data = _data_extenso(d.group(1)) if d else None
        r2 = re.search(r'<a[^>]*detalhes/' + nid + r'/[^>]*>([\s\S]{20,900}?)</a>', trecho)
        guardar(nid, titulo, url, data, r2.group(1) if r2 else "")

    # lista do meio
    for m in re.finditer(r'<div class="item-lista-noticia">([\s\S]{100,2500}?)</h3>', pagina):
        bloco = m.group(1)
        link = re.search(r'<a\s+href="([^"]*detalhes/(\d+)/[^"]*)"[^>]*>([\s\S]*?)</a>', bloco)
        if not link:
            continue
        dnum = re.search(r"(\d{1,2}/\d{1,2}/\d{4})", bloco)
        guardar(link.group(2), link.group(3), link.group(1),
                _data_numerica(dnum.group(1)) if dnum else None)

    # qualquer h3 com link de detalhe (rede de segurança)
    for m in re.finditer(
            r'<h3[^>]*>\s*<a\s+href="([^"]*detalhes/(\d+)/[^"]*)"[^>]*>([\s\S]*?)</a>',
            pagina):
        url, nid, titulo = m.group(1), m.group(2), m.group(3)
        if nid in itens:
            continue
        trecho = pagina[max(0, m.start() - 800):m.start() + 800]
        d = re.search(r"(\d{1,2}/\d{1,2}/\d{4})", trecho)
        guardar(nid, titulo, url, _data_numerica(d.group(1)) if d else None)

    lista = [itens[i] for i in ordem]
    lista.sort(key=lambda x: x["data"], reverse=True)
    return lista


def noticias(limite=12):
    """Lista de notícias com cache. Nunca levanta exceção: em falha devolve
    o último resultado bom e o motivo, para a tela poder avisar."""
    agora = time.time()
    if _cache["itens"] and (agora - _cache["quando"]) < CACHE_SEGUNDOS:
        return _cache["itens"][:limite], _cache["erro"]

    try:
        itens = extrair_noticias(_baixar())
        if itens:
            _cache.update(quando=agora, itens=itens, erro=None)
        else:
            _cache["erro"] = "a página da ABCCC respondeu sem notícias reconhecíveis"
        return _cache["itens"][:limite], _cache["erro"]
    except Exception as e:
        _cache["erro"] = f"não foi possível ler a ABCCC ({type(e).__name__})"
        return _cache["itens"][:limite], _cache["erro"]


# ---------------------------------------------------------------- matéria
# A notícia inteira é lida do site da ABCCC para ser mostrada DENTRO do
# portal (o dono pediu para não mandar o visitante para fora). O texto
# continua sendo da Associação: a tela mostra autor, data e o link da
# fonte, e o portal não se apresenta como autor da matéria.
_cache_materia = {}          # id -> {'quando', 'materia'}
CACHE_MATERIA = 60 * 60 * 6  # 6 horas


def _texto_do_html(seg):
    """Converte um trecho de HTML em texto legível, preservando parágrafos."""
    seg = re.sub(r"<script[\s\S]*?</script>", " ", seg)
    seg = re.sub(r"<style[\s\S]*?</style>", " ", seg)
    # quebras onde o HTML indica fim de bloco
    seg = re.sub(r"<(?:br|/p|/div|/h[1-6]|/li|/tr)\s*[^>]*>", "\n", seg, flags=re.I)
    seg = re.sub(r"<[^>]+>", " ", seg)
    seg = htmlmod.unescape(seg).replace("\xa0", " ")
    seg = re.sub(r"[ \t]+", " ", seg)
    seg = re.sub(r"\n[ ]*\n+", "\n\n", seg)
    linhas = [l.strip() for l in seg.split("\n")]
    return "\n\n".join([l for l in linhas if l])


def extrair_materia(pagina, url=""):
    """Título, data, autor e corpo de uma página de notícia da ABCCC."""
    out = {"url": url, "titulo": "", "data": None, "autor": "",
           "corpo": "", "paragrafos": [], "fonte": "ABCCC — cavalocrioulo.org.br"}

    m = re.search(r"<title>([\s\S]*?)</title>", pagina)
    if m:
        out["titulo"] = htmlmod.unescape(_limpa(m.group(1)))

    m = re.search(r"<h1[^>]*>([\s\S]*?)</h1>", pagina)
    if m:
        t = htmlmod.unescape(_limpa(m.group(1)))
        if len(t) > 10:
            out["titulo"] = t

    # data e autor ficam logo abaixo do título
    m = re.search(r"(\d{1,2}\s+DE\s+[A-Za-zÀ-ÿ]+\s+DE\s+\d{4})", pagina)
    if m:
        out["data"] = _data_extenso(m.group(1))

    m = re.search(r"Redator\s*:?\s*(?:</?[^>]+>\s*)*([A-Za-zÀ-ÿ0-9 .,'\-]{3,60})", pagina)
    if m:
        autor = _limpa(m.group(1)).strip(" .–-")
        if autor and not autor.lower().startswith("redator"):
            out["autor"] = autor[:60]

    # corpo: tudo do container da matéria até o bloco de publicidade
    i = pagina.find("conteudo-noticia")
    if i > 0:
        trecho = pagina[i:i + 60000]
        for marca in ("publicidade", "rn-links", "itemBa", "newsletter"):
            j = trecho.find(marca)
            if j > 500:
                trecho = trecho[:j]
                break
        texto = _texto_do_html(trecho)
        linhas = [l for l in texto.split("\n\n") if len(l) > 2]

        # tira resíduos que não são texto da matéria: o nome da classe,
        # sobra de tag e o convite de "encontrou erro" do próprio site
        def lixo(l):
            baixo = l.lower()
            if "conteudo-noticia" in baixo or "class=" in baixo:
                return True
            if baixo.startswith("encontrou algum erro"):
                return True
            if l.startswith(">>") or l.startswith("<<"):
                return True
            if re.fullmatch(r"[\W_]+", l):
                return True
            return False

        linhas = [l for l in linhas if not lixo(l)]
        out["paragrafos"] = linhas
        out["corpo"] = "\n\n".join(linhas)

    return out


def materia(nid, url=""):
    """Matéria completa com cache. Nunca levanta exceção."""
    if not nid or not re.fullmatch(r"\d{2,12}", str(nid)):
        return None, "notícia inválida"
    agora = time.time()
    guardada = _cache_materia.get(nid)
    if guardada and (agora - guardada["quando"]) < CACHE_MATERIA:
        return guardada["materia"], None

    if not url:
        itens, _ = noticias(50)
        achado = next((x for x in itens if str(x["id"]) == str(nid)), None)
        url = achado["url"] if achado else None
    if not url:
        return None, "não encontrei esta notícia na lista da ABCCC"

    try:
        m = extrair_materia(_baixar(url), url)
        if not m["corpo"]:
            return None, "a página da ABCCC não trouxe o texto da matéria"
        _cache_materia[nid] = {"quando": agora, "materia": m}
        return m, None
    except Exception as e:
        if guardada:
            return guardada["materia"], None
        return None, f"não foi possível ler a matéria ({type(e).__name__})"


if __name__ == "__main__":
    import sys
    if "--json" in sys.argv:
        print(json.dumps(noticias()[0], ensure_ascii=False, indent=1))
    else:
        lista, erro = noticias()
        print(f"{len(lista)} notícia(s)" + (f" · aviso: {erro}" if erro else "") + "\n")
        for x in lista:
            print(f"[{x['data']}] {x['titulo']}")
            if x["resumo"]:
                print(f"   {x['resumo'][:140]}")
            print(f"   {x['url']}\n")
