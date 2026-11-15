"""Servidor: api.py + SEO por pagina + sitemap do banco.

api.py ja esta publicado: aqui ele e apenas ENVOLVIDO, nenhuma rota muda.
O gunicorn sobe wsgi:app no lugar de api:app (Procfile e railway.json).

Antes, toda URL devolvia o MESMO titulo e o mesmo HTML: para o Google,
/cavalos, /cavalo/213 e /rankings eram a mesma pagina, e pagina duplicada
nao e indexada. Aqui o servidor monta titulo, descricao, canonica, Open
Graph e JSON-LD da URL pedida, e publica um sitemap com uma URL por animal.

Sem banco nada quebra: sitemap so com as paginas fixas e HTML como veio.
"""
import html
import json
import re

from flask import Response, request

import api

app = api.app
BASE = "https://proprietario.net"

FIXAS = {
    "": ("Freio do Proprietario | Cavalo Crioulo - rankings e resultados",
         "Rankings por ciclo e categoria, provas, resultados, cavalos e ginetes do "
         "Freio do Proprietario do Cavalo Crioulo. Consulte qualquer animal pelo nome.",
         "1.0", "daily"),
    "rankings": ("Rankings do Freio do Proprietario | Cavalo Crioulo",
                 "Ranking oficial de cada ciclo e categoria: pontos, habilitacao e "
                 "melhor nota de cada conjunto ginete e cavalo crioulo.", "0.9", "daily"),
    "final": ("Final do Freio do Proprietario | Cavalo Crioulo",
              "Catalogo, sumula e podio da Final: classificados, notas por etapa e "
              "cavalos transferidos.", "0.8", "weekly"),
    "provas": ("Provas e credenciadoras do Freio do Proprietario",
               "Provas por ciclo, com data, cidade, inscritos e resultado de cada "
               "categoria.", "0.8", "daily"),
    "credenciadoras": ("Calendario de credenciadoras | Freio do Proprietario",
                       "Onde e quando ha prova do Freio do Proprietario do Cavalo "
                       "Crioulo. Agenda por cidade e data, com exportacao para o seu "
                       "calendario.", "0.7", "weekly"),
    "competidores": ("Ginetes do Freio do Proprietario | Cavalo Crioulo",
                     "Ginetes: provas disputadas, vitorias, melhor nota e cavalos "
                     "montados.", "0.7", "weekly"),
    "cavalos": ("Cavalos Crioulos do Freio do Proprietario | Busca por nome",
                "Consulte cavalos crioulos por nome, registro, criador ou proprietario. "
                "Ficha com historico de provas e notas.", "0.8", "weekly"),
    "meus-cavalos": ("Meus cavalos | Freio do Proprietario",
                     "Encontre os cavalos de um proprietario pelo nome: plantel, "
                     "pontos, habilitacao e melhor nota.", "0.6", "monthly"),
    "como-funciona": ("Como funciona o Freio do Proprietario | Regras e etapas",
                      "O conjunto, as etapas e os tetos de nota, o calculo da media da "
                      "prova e por que 12 pontos habilitam.", "0.6", "monthly"),
    "estatisticas": ("Estatisticas do Freio do Proprietario | Cavalo Crioulo",
                     "Conjuntos, notas, medias e desempenho por categoria e por ciclo.",
                     "0.6", "weekly"),
    "jurados": ("Jurados do Freio do Proprietario",
                "Jurados que atuam nas provas e as provas de que participaram.",
                "0.5", "monthly"),
    "noticias": ("Noticias do Cavalo Crioulo | ABCCC",
                 "Publicacoes da Associacao Brasileira de Criadores de Cavalos "
                 "Crioulos sobre o Freio do Proprietario e a raca.", "0.7", "daily"),
}

_T = re.compile(r"<title>.*?</title>", re.S | re.I)
_D = re.compile(r'<meta name="description"[^>]*>', re.I)
_H = re.compile(r"</head>", re.I)


def _c(s, n=300):
    return re.sub(r"\s+", " ", str(s or "")).strip()[:n].rstrip(" ,;.-")


def _n(v):
    try:
        return ("%.3f" % float(v)).replace(".", ",")
    except (TypeError, ValueError):
        return None


def _injetar(pagina, titulo, desc, caminho, ld=None, tipo="website"):
    url = BASE + "/" + caminho
    t, d = html.escape(_c(titulo, 120)), html.escape(_c(desc, 300))
    s = _T.sub(lambda m: "<title>" + t + "</title>", pagina, count=1)
    tag = '<meta name="description" content="' + d + '">'
    s = (_D.sub(lambda m: tag, s, count=1) if _D.search(s)
         else s.replace("</title>", "</title>\n" + tag, 1))
    b = "\n".join([
        '<link rel="canonical" href="' + url + '">',
        '<meta property="og:url" content="' + url + '">',
        '<meta property="og:type" content="' + tipo + '">',
        '<meta property="og:title" content="' + t + '">',
        '<meta property="og:description" content="' + d + '">',
        '<meta property="og:image" content="' + BASE + '/og.png">',
        '<meta property="og:site_name" content="Portal Freio do Proprietario">',
        '<meta name="twitter:card" content="summary_large_image">',
        '<meta name="robots" content="index, follow, max-image-preview:large">"])
    if ld:
        b += ('\n<script type="application/ld+json">'
              + json.dumps(ld, ensure_ascii=False) + "</script>")
    return _H.sub(lambda m: "\n" + b + "\n</head>", s, count=1)


def _cavalo(aid):
    r = api.consultar("""select a.nome, a.registro, a.pelagem, a.criador,
             a.proprietario, to_char(a.nascimento,'YYYY') ano
             from animal a where a.id = %s""", (aid,))
    if not r:
        return None
    a = r[0]
    rk = api.consultar("""select count(*) provas, max(x.media) melhor
             from resultado x join inscricao i on i.id = x.inscricao_id
            where i.animal_id = %s and x.origem <> 'final'""", (aid,))
    provas = (rk[0]["provas"] or 0) if rk else 0
    melhor = _n(rk[0]["melhor"]) if rk else None
    p = []
    if a.get("registro"):
        p.append("registro " + str(a["registro"]))
    if a.get("pelagem"):
        p.append(str(a["pelagem"]).lower())
    if a.get("ano"):
        p.append("nascido em " + str(a["ano"]))
    if a.get("criador"):
        p.append("criador " + str(a["criador"]))
    if a.get("proprietario"):
        p.append("proprietario " + str(a["proprietario"]))
    esp = ""
    if provas:
        esp = (" %d apresenta%s no Freio do Proprietario%s."
               % (provas, "cao" if provas == 1 else "coes",
                  (", melhor nota " + melhor) if melhor else ""))
    ld = {"@context": "https://schema.org", "@type": "WebPage",
          "name": a["nome"], "url": BASE + "/cavalo/%s" % aid,
          "inLanguage": "pt-BR",
          "mainEntity": {"@type": "Thing", "name": a["nome"],
                         "description": "Cavalo Crioulo"
                         + (" de registro " + str(a["registro"])
                            if a.get("registro") else "")}}
    return (a["nome"] + " - cavalo crioulo | Freio do Proprietario",
            a["nome"] + " (cavalo crioulo" + (", " + ", ".join(p) if p else "")
            + ")." + esp, ld)


def _prova(eid):
    r = api.consultar("""select nome, to_char(data_inicio,'DD/MM/YYYY') data,
             cidade, uf, (select count(*) from inscricao i where i.evento_id = e.id)
             inscritos from evento e where e.id = %s""", (eid,))
    if not r:
        return None
    e = r[0]
    loc = ", ".join(str(x) for x in [e.get("cidade"), e.get("uf")] if x)
    ld = {"@context": "https://schema.org", "@type": "SportsEvent",
          "name": e["nome"], "url": BASE + "/prova/" + str(eid),
          "sport": "Freio do Proprietario"}
    if e.get("cidade"):
        ld["location"] = {"@type": "Place", "name": loc,
                          "address": {"@type": "PostalAddress",
                                      "addressLocality": e.get("cidade"),
                                      "addressRegion": e.get("uf"),
                                      "addressCountry": "BR"}}
    return (e["nome"] + (" - " + e["cidade"] if e.get("cidade") else "")
            + " | Freio do Proprietario",
            "%s%s%s. %s inscritos. Resultado por categoria e notas por etapa."
            % (e["nome"], (", em " + loc) if loc else "",
               (", dia " + e["data"]) if e.get("data") else "", e["inscritos"]),
            ld)


def _competidor(pid):
    r = api.consultar("""select p.nome, p.cidade, p.uf,
             (select count(*) from inscricao i where i.pessoa_id = p.id) aps
             from pessoa p where p.id = %s""", (pid,))
    if not r:
        return None
    p = r[0]
    loc = ", ".join(str(x) for x in [p.get("cidade"), p.get("uf")] if x)
    ld = {"@context": "https://schema.org", "@type": "Person",
          "name": p["nome"], "url": BASE + "/competidor/%s" % pid,
          "jobTitle": "Ginete"}
    return (p["nome"] + " - ginete | Freio do Proprietario",
            "%s%s. %s apresentacoes no Freio do Proprietario, com provas, resultados "
            "e cavalos montados."
            % (p["nome"], (", de " + loc) if loc else "", p["aps"]), ld)


def pagina_seo(caminho, pagina):
    """HTML com as marcas daquela pagina. Nunca lanca."""
    try:
        ps = [x for x in (caminho or "").split("/") if x]
        if not ps:
            ld = {"@context": "https://schema.org", "@type": "WebSite",
                  "name": "Portal Freio do Proprietario", "url": BASE + "/",
                  "inLanguage": "pt-BR",
                  "potentialAction": {
                      "@type": "SearchAction",
                      "target": BASE + "/cavalos?q={search_term_string}",
                      "query-input": "required name=search_term_string"}}
            return _injetar(pagina, FIXAS[""][0], FIXAS[""][1], "", ld)
        raiz = ps[0].lower()
        if raiz == "cavalo" and len(ps) > 1 and ps[1].isdigit():
            x = _cavalo(int(ps[1]))
            if x:
                return _injetar(pagina, x[0], x[1], "/".join(ps), x[2], "profile")
        if raiz == "prova" and len(ps) > 1 and ps[1].isdigit():
            x = _prova(int(ps[1]))
            if x:
                return _injetar(pagina, x[0], x[1], "/".join(ps), x[2], "article")
        if raiz == "competidor" and len(ps) > 1 and ps[1].isdigit():
            x = _competidor(int(ps[1]))
            if x:
                return _injetar(pagina, x[0], x[1], "/".join(ps), x[2], "profile")
        if raiz in FIXAS:
            t, d = FIXAS[raiz][0], FIXAS[raiz][1]
            ld = {"@context": "https://schema.org", "@type": "WebPage",
                  "name": t, "url": BASE + "/" + raiz, "inLanguage": "pt-BR"}
            return _injetar(pagina, t, d, raiz, ld)
    except Exception as e:
        print("[seo] aviso:", str(e)[:150], flush=True)
    return pagina


@app.before_request
def _sitemap():
    if request.path != "/sitemap.xml":
        return None
    u = []

    def add(c, pr, f):
        u.append("<url><loc>%s/%s</loc><changefreq>%s</changefreq>"
                 "<priority>%s</priority></url>" % (BASE, c, f, pr))

    for c, v in FIXAS.items():
        add(c, v[2], v[3])
    try:
        for a in api.consultar("select id from animal order by id"):
            add("cavalo/%s" % a["id"], "0.6", "monthly")
        for p in api.consultar("""select p.id from pessoa p where exists
                 (select 1 from inscricao i where i.pessoa_id = p.id) order by p.id"""):
            add("competidor/%s" % p["id"], "0.5", "monthly")
        for e in api.consultar("select id from evento order by id"):
            add("prova/%s" % e["id"], "0.5", "weekly")
    except Exception as ex:
        print("[sitemap] so fixas:", str(ex)[:120], flush=True)
    return Response('<?xml version="1.0" encoding="UTF-8"?>'
                    '<urlset xmlns="http://www.sitemaps.org/schemas/sitemap/0.9">'
                    + "".join(u) + "</urlset>", mimetype="application/xml")


@app.after_request
def _seo(resp):
    try:
        if resp.mimetype != "text/html" or not (200 <= resp.status_code < 300):
            return resp
        if request.path.startswith("/api"):
            return resp
        u = request.path.rstrip("/").split("/")[-1]
        if "." in u and u != "index.html":
            return resp
        orig = resp.get_data(as_text=True)
        novo = pagina_seo(request.path.strip("/"), orig)
        if novo != orig:
            resp.set_data(novo)
    except Exception as e:
        print("[seo] desligado:", str(e)[:160], flush=True)
    return resp
