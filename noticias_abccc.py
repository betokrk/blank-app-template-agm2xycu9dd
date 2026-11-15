#!/usr/bin/env python3
"""Notícias da ABCCC dentro do portal (sem RSS — a ABCCC não publica feed).

Por que não RSS: o site oficial (cavalocrioulo.org.br) responde HTML em
/feed/, /rss, /rss.xml e /noticias/feed/. Não existe feed para assinar.

O que este módulo faz:
  - lê a página pública de notícias da ABCCC e extrai título, data, resumo
    e link de cada item;
  - guarda em cache por CACHE_SEGUNDOS para não bater no site a cada visita;
  - se a ABCCC estiver fora do ar, devolve o último resultado bom (nunca
    inventa notícia nem mostra lista vazia por falha momentânea).

O conteúdo é sempre da ABCCC e o portal mostra a fonte e o link original.
Não copiamos o texto inteiro: título, resumo curto e o link.
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


def _baixar():
    req = urllib.request.Request(URL_NOTICIAS, headers={"User-Agent": UA})
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
