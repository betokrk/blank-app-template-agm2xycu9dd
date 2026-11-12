#!/usr/bin/env python3
"""
API do Portal Freio do Proprietário.

Princípios:
  - Postgres puro, sem recurso proprietário de provedor.
  - A leitura pública vem de VIEWS (vw_*), nunca de tabela crua.
  - Toda escrita passa por aqui: permissão decidida no servidor, não na tela.
  - Senha guarda hash (pbkdf2), nunca texto.
  - Sessão é token opaco em tabela, com validade.
"""
import json
import os
import re
import secrets
import sys
from datetime import datetime, timedelta
from functools import wraps
from hashlib import pbkdf2_hmac

from flask import Flask, jsonify, request, send_from_directory, g

RAIZ = os.path.dirname(os.path.abspath(__file__))
ESTATICO = os.path.join(RAIZ, "static")

app = Flask(__name__, static_folder=None)
app.config["JSON_SORT_KEYS"] = False

# --------------------------------------------------------------------- banco


def db():
    if "db" not in g:
        import psycopg2
        import psycopg2.extras
        url = os.environ.get("DATABASE_URL")
        if not url:
            raise RuntimeError("DATABASE_URL não definida")
        g.db = psycopg2.connect(url)
        g.db.autocommit = False
    return g.db


@app.teardown_appcontext
def fecha_db(exc):
    con = g.pop("db", None)
    if con is not None:
        con.close()


def consultar(sql, params=(), um=False):
    import psycopg2.extras
    with db().cursor(cursor_factory=psycopg2.extras.RealDictCursor) as cur:
        cur.execute(sql, params)
        linhas = cur.fetchall()
        return (linhas[0] if linhas else None) if um else linhas


def executar(sql, params=()):
    """Executa e devolve o cursor AINDA ABERTO (o caller precisa do
    returning). Quem chama usa fetchone() e o cursor é fechado no fim da
    requisição, junto com a conexão."""
    cur = db().cursor()
    cur.execute(sql, params)
    return cur


# --------------------------------------------------------------------- senha


def hash_senha(senha, sal=None):
    sal = sal or secrets.token_hex(16)
    h = pbkdf2_hmac("sha256", senha.encode(), sal.encode(), 200_000).hex()
    return f"pbkdf2${sal}${h}"


def confere_senha(senha, guardado):
    try:
        _, sal, h = guardado.split("$")
    except ValueError:
        return False
    calc = pbkdf2_hmac("sha256", senha.encode(), sal.encode(), 200_000).hex()
    return secrets.compare_digest(calc, h)


# --------------------------------------------------------------------- sessão

PAPEIS_ESCRITA = ("editor", "admin", "superadmin")


def usuario_atual():
    tok = request.headers.get("Authorization", "").replace("Bearer ", "").strip()
    if not tok:
        return None
    linha = consultar(
        """select u.id, u.nome, u.email, u.papel
             from sessao s join usuario u on u.id = s.usuario_id
            where s.token = %s and s.expira_em > now() and u.ativo""",
        (tok,), um=True)
    return linha


def exige(*papeis):
    def deco(fn):
        @wraps(fn)
        def wrapper(*a, **kw):
            u = usuario_atual()
            if not u:
                return jsonify(erro="Entre para continuar."), 401
            if papeis and u["papel"] not in papeis:
                return jsonify(erro="Seu perfil não permite esta ação."), 403
            g.usuario = u
            return fn(*a, **kw)
        return wrapper
    return deco


def auditar(acao, entidade, entidade_id=None, anterior=None, novo=None, motivo=None, fonte=None):
    u = getattr(g, "usuario", None)
    executar(
        """insert into auditoria (usuario_id, usuario_nome, acao, entidade, entidade_id,
                                  anterior, novo, motivo, fonte)
           values (%s,%s,%s,%s,%s,%s,%s,%s,%s)""",
        (u["id"] if u else None, u["nome"] if u else "sistema", acao, entidade,
         str(entidade_id) if entidade_id is not None else None,
         json.dumps(anterior, default=str) if anterior else None,
         json.dumps(novo, default=str) if novo else None, motivo, fonte))


# --------------------------------------------------------------------- saúde


@app.get("/api/saude")
def saude():
    try:
        n = consultar("select count(*) c from animal", um=True)["c"]
        v = consultar("select max(versao) v from schema_version", um=True)["v"]
        return jsonify(ok=True, animais=n, versao_banco=v)
    except Exception as e:
        return jsonify(ok=False, erro=str(e)[:200]), 500


# --------------------------------------------------------------------- leitura


@app.get("/api/ciclos")
def ciclos():
    return jsonify(consultar("""
        select c.id, c.nome, c.disponivel, c.documento,
               coalesce(n.conjuntos,0) as conjuntos,
               coalesce(n.habilitados,0) as habilitados,
               coalesce(n.animais,0) as animais,
               coalesce(n.pessoas,0) as pessoas
          from ciclo c
          left join vw_ciclo_numeros n on n.ciclo = c.id
         order by c.id desc"""))


@app.get("/api/categorias")
def categorias():
    return jsonify(consultar("select id, nome, grupo, idade from categoria order by ordem"))


@app.get("/api/ranking")
def ranking():
    ciclo = request.args.get("ciclo", "2026")
    cat = request.args.get("categoria")
    sql = """select * from vw_ranking
             where ciclo = %s and origem <> 'final'"""
    p = [ciclo]
    if cat:
        sql += " and categoria = %s"
        p.append(cat)
    sql += " order by categoria, posicao nulls last, media desc"
    return jsonify(consultar(sql, p))


@app.get("/api/final")
def final():
    ciclo = request.args.get("ciclo", "2026")
    return jsonify({
        "evento": consultar("""
            select e.nome, e.local, e.data_inicio, e.data_fim, e.documento,
                   f.conjuntos_inscritos, f.tem_classificacao
              from evento e left join final f on f.ciclo_id = e.ciclo_id
             where e.tipo='final' and e.ciclo_id = %s""", (ciclo,), um=True),
        "resultados": consultar("""
            select * from vw_ranking
             where ciclo = %s and origem='final'
             order by categoria, posicao nulls last, media desc""", (ciclo,)),
        "comercializados": consultar(
            "select * from vw_comercializados where ciclo = %s order by animal", (ciclo,)),
        "multi": consultar(
            "select * from vw_ginetes_multi where ciclo = %s order by animais desc", (ciclo,)),
    })


@app.get("/api/comparativo")
def comparativo():
    ciclo = request.args.get("ciclo", "2026")
    return jsonify(consultar("""
        select * from vw_comparativo_final where ciclo = %s
        order by categoria, posicao_final nulls last""", (ciclo,)))


@app.get("/api/calendario")
def calendario():
    return jsonify(consultar(
        "select cidade, data, tipo from calendario_prova where data >= current_date order by data"))


@app.get("/api/cavalos")
def cavalos():
    busca = request.args.get("q", "").strip()
    limite = min(int(request.args.get("limite", 50)), 200)
    if busca:
        return jsonify(consultar("""
            select id, nome, registro, rg, sexo, pelagem, criador
              from animal where nome_norm like %s order by nome limit %s""",
            ("%" + re.sub(r"\s+", " ", busca.lower()) + "%", limite)))
    return jsonify(consultar(
        "select id, nome, registro from animal order by nome limit %s", (limite,)))


@app.get("/api/pessoas")
def pessoas():
    busca = request.args.get("q", "").strip()
    limite = min(int(request.args.get("limite", 50)), 200)
    p = "%" + busca.lower() + "%"
    return jsonify(consultar("""
        select id, nome, profissao, cidade, uf from pessoa
         where (%s = '' or nome_norm like %s) order by nome limit %s""",
        (busca, p, limite)))


@app.get("/api/banners")
def banners():
    return jsonify(consultar("select id, titulo, texto, link, imagem_url, cor, posicao from vw_banner_ativo"))


@app.post("/api/banner/<int:bid>/clique")
def banner_clique(bid):
    executar("update banner set cliques = cliques + 1 where id = %s", (bid,))
    db().commit()
    return jsonify(ok=True)


@app.post("/api/busca")
def busca_log():
    d = request.get_json(silent=True) or {}
    termo = (d.get("termo") or "").strip()[:60]
    if termo:
        executar("insert into busca_log (termo) values (%s)", (termo,))
        db().commit()
    return jsonify(ok=True)


@app.get("/api/config")
def config_publica():
    c = consultar("select logo_url, logo_letra, nome_exibido from config_portal where id=1", um=True)
    return jsonify(c or {})


@app.put("/api/admin/config")
@exige(*PAPEIS_ESCRITA)
def admin_config_salvar():
    d = request.get_json(silent=True) or {}
    antes = consultar("select * from config_portal where id=1", um=True)
    executar("""
        insert into config_portal (id, logo_url, logo_letra, nome_exibido, atualizado_em)
        values (1,%s,%s,%s, now())
        on conflict (id) do update set
          logo_url = coalesce(excluded.logo_url, config_portal.logo_url),
          logo_letra = coalesce(excluded.logo_letra, config_portal.logo_letra),
          nome_exibido = coalesce(excluded.nome_exibido, config_portal.nome_exibido),
          atualizado_em = now()""",
        (d.get("logo_url"), d.get("logo_letra"), d.get("nome_exibido")))
    auditar("editar", "config_portal", 1, antes, d, "Logo do portal")
    db().commit()
    return jsonify(ok=True)


@app.post("/api/visita")
def visita():
    d = request.get_json(silent=True) or {}
    pagina = str(d.get("pagina", "inicio"))[:60]
    executar("""
        insert into visita_dia (dia, pagina, visitas) values (current_date, %s, 1)
        on conflict (dia, pagina) do update set visitas = visita_dia.visitas + 1""", (pagina,))
    db().commit()
    return jsonify(ok=True)


# --------------------------------------------------------------------- login


@app.post("/api/entrar")
def entrar():
    d = request.get_json(silent=True) or {}
    email = (d.get("email") or "").strip().lower()
    senha = d.get("senha") or ""
    u = consultar("select * from usuario where lower(email) = %s and ativo", (email,), um=True)
    if not u or not confere_senha(senha, u["senha_hash"]):
        return jsonify(erro="E-mail ou senha não conferem."), 401
    tok = secrets.token_urlsafe(32)
    executar("insert into sessao (token, usuario_id, expira_em) values (%s,%s,%s)",
             (tok, u["id"], datetime.now() + timedelta(days=7)))
    executar("update usuario set ultimo_acesso = now() where id = %s", (u["id"],))
    db().commit()
    return jsonify(token=tok, usuario={"id": u["id"], "nome": u["nome"], "papel": u["papel"]})


@app.post("/api/sair")
def sair():
    tok = request.headers.get("Authorization", "").replace("Bearer ", "").strip()
    if tok:
        executar("delete from sessao where token = %s", (tok,))
        db().commit()
    return jsonify(ok=True)


@app.get("/api/eu")
def eu():
    return jsonify(usuario=usuario_atual())


# --------------------------------------------------------------------- admin


@app.get("/api/admin/visao")
@exige(*PAPEIS_ESCRITA)
def admin_visao():
    return jsonify({
        "animais": consultar("select count(*) c from animal", um=True)["c"],
        "pessoas": consultar("select count(*) c from pessoa", um=True)["c"],
        "inscricoes": consultar("select count(*) c from inscricao", um=True)["c"],
        "importacoes": consultar(
            "select id, arquivo, formato, linhas, criados, atualizados, rejeitados, criado_em"
            " from importacao order by id desc limit 10"),
        "banners": consultar("select count(*) c from banner", um=True)["c"],
        "auditoria": consultar(
            "select quando, usuario_nome, acao, entidade, motivo from auditoria"
            " order by id desc limit 10"),
    })


# ---------------------------- banners do admin


@app.get("/api/admin/banners")
@exige(*PAPEIS_ESCRITA)
def admin_banners():
    return jsonify(consultar(
        "select * from banner order by posicao, id"))


@app.post("/api/admin/banners")
@exige(*PAPEIS_ESCRITA)
def admin_banner_criar():
    d = request.get_json(silent=True) or {}
    if not (d.get("titulo") or "").strip():
        return jsonify(erro="Informe o título."), 400
    pos = d.get("posicao", "topo")
    if pos not in ("topo", "listas", "lateral", "rodape"):
        return jsonify(erro="Posição inválida."), 400
    cur = executar("""
        insert into banner (titulo, texto, link, imagem_url, cor, posicao, inicio, fim, ativo)
        values (%s,%s,%s,%s,%s,%s,%s,%s,%s) returning id""",
        (d["titulo"].strip(), d.get("texto"), d.get("link"), d.get("imagem_url"),
         d.get("cor"), pos, d.get("inicio") or None, d.get("fim") or None,
         d.get("ativo", True)))
    novo_id = cur.fetchone()[0]
    auditar("criar", "banner", novo_id, None, d)
    db().commit()
    return jsonify(ok=True, id=novo_id)


@app.put("/api/admin/banners/<int:bid>")
@exige(*PAPEIS_ESCRITA)
def admin_banner_editar(bid):
    d = request.get_json(silent=True) or {}
    antes = consultar("select * from banner where id = %s", (bid,), um=True)
    if not antes:
        return jsonify(erro="Banner não encontrado."), 404
    executar("""update banner set titulo=%s, texto=%s, link=%s, imagem_url=%s, cor=%s,
                posicao=%s, inicio=%s, fim=%s, ativo=%s, atualizado_em=now()
                where id=%s""",
             (d.get("titulo", antes["titulo"]), d.get("texto", antes["texto"]),
              d.get("link", antes["link"]), d.get("imagem_url", antes["imagem_url"]),
              d.get("cor", antes["cor"]), d.get("posicao", antes["posicao"]),
              d.get("inicio") or None, d.get("fim") or None,
              d.get("ativo", antes["ativo"]), bid))
    auditar("editar", "banner", bid, antes, d)
    db().commit()
    return jsonify(ok=True)


@app.delete("/api/admin/banners/<int:bid>")
@exige(*PAPEIS_ESCRITA)
def admin_banner_apagar(bid):
    antes = consultar("select * from banner where id = %s", (bid,), um=True)
    if not antes:
        return jsonify(erro="Banner não encontrado."), 404
    executar("delete from banner where id = %s", (bid,))
    auditar("apagar", "banner", bid, antes, None)
    db().commit()
    return jsonify(ok=True)


# ---------------------------- analytics


@app.get("/api/admin/analytics")
@exige(*PAPEIS_ESCRITA)
def admin_analytics():
    return jsonify({
        "dias": consultar("""
            select dia, sum(visitas)::int as visitas from visita_dia
             where dia >= current_date - interval '14 days'
             group by dia order by dia"""),
        "paginas": consultar("select * from vw_analytics_pagina limit 10"),
        "buscas": consultar("""
            select termo, count(*)::int as n from busca_log
             where dia >= current_date - interval '30 days'
             group by termo order by n desc limit 10"""),
    })


# ---------------------------- importação (Maestro)


@app.post("/api/admin/importar")
@exige(*PAPEIS_ESCRITA)
def admin_importar():
    """Recebe linhas já interpretadas pelo app (CSV lido no navegador ou
    resposta da IA) e grava no banco. Nada entra sem esta chamada, e cada
    linha é validada antes do insert."""
    d = request.get_json(silent=True) or {}
    linhas = d.get("linhas") or []
    modelo = d.get("modelo")
    evento_chave = d.get("evento_chave")
    arquivo = (d.get("arquivo") or "importação")[:120]

    if not linhas:
        return jsonify(erro="Nenhuma linha para importar."), 400

    ev = consultar("select id, ciclo_id from evento where chave = %s", (evento_chave,), um=True)
    if not ev:
        return jsonify(erro="Evento de destino não encontrado."), 400

    criados = atualizados = rejeitados = 0
    erros = []

    fim_cobertura = consultar("select 1 from evento where chave='final-2026'")

    for i, ln in enumerate(linhas):
        try:
            cat = (ln.get("categoria") or "").strip()
            if not consultar("select 1 from categoria where id=%s", (cat,), um=True):
                rejeitados += 1
                erros.append({"linha": i + 2, "motivo": "categoria desconhecida"})
                continue
            nome_animal = (ln.get("cavalo") or "").strip()
            if not nome_animal:
                rejeitados += 1
                erros.append({"linha": i + 2, "motivo": "cavalo vazio"})
                continue

            nome_norm = re.sub(r"\s+", " ", re.sub(r"[^a-z0-9]+", " ",
                                                     nome_animal.lower())).strip()
            cur = executar("""
                insert into animal (nome, nome_norm, fonte, selo)
                values (%s,%s,%s,'informado')
                on conflict (nome_norm) do update set atualizado_em = now()
                returning id""", (nome_animal, nome_norm, arquivo))
            animal_id = cur.fetchone()[0]

            pessoa_id = None
            if (ln.get("ginete") or "").strip():
                pn = (ln["ginete"]).strip()
                pnn = re.sub(r"\s+", " ", re.sub(r"[^a-z0-9]+", " ", pn.lower())).strip()
                cur = executar("""
                    insert into pessoa (nome, nome_norm, fonte, selo)
                    values (%s,%s,%s,'informado')
                    on conflict (nome_norm) do update set atualizado_em = now()
                    returning id""", (pn, pnn, arquivo))
                pessoa_id = cur.fetchone()[0]

            cur = executar("""
                insert into inscricao (evento_id, ciclo_id, categoria_id, animal_id,
                                       pessoa_id, box, status, fonte, selo)
                values (%s,%s,%s,%s,%s,%s,'importado',%s,'informado')
                on conflict (evento_id, categoria_id, animal_id) do update set
                  pessoa_id = coalesce(excluded.pessoa_id, inscricao.pessoa_id),
                  box = coalesce(excluded.box, inscricao.box),
                  atualizado_em = now()
                returning id, (xmax = 0) as novo""",
                (ev["id"], ev["ciclo_id"], cat, animal_id, pessoa_id,
                 ln.get("box"), arquivo))
            ins_id, novo = cur.fetchone()
            if novo:
                criados += 1
            else:
                atualizados += 1

            orig = "final" if evento_chave and "final" in evento_chave else "credenciadora"
            executar("""
                insert into resultado (inscricao_id, evento_id, ciclo_id, categoria_id,
                    posicao, posicao_oficial, media, soma, pontos, pontos_oficiais,
                    habilitado, concluiu, origem, fonte, selo)
                values (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,'informado')
                on conflict (inscricao_id) do update set
                  posicao = coalesce(excluded.posicao, resultado.posicao),
                  posicao_oficial = coalesce(excluded.posicao_oficial, resultado.posicao_oficial),
                  media = coalesce(excluded.media, resultado.media),
                  soma = coalesce(excluded.soma, resultado.soma),
                  pontos = coalesce(excluded.pontos, resultado.pontos),
                  habilitado = coalesce(excluded.habilitado, resultado.habilitado),
                  atualizado_em = now()""",
                (ins_id, ev["id"], ev["ciclo_id"], cat,
                 ln.get("posicao"), ln.get("posicao"), ln.get("media"), ln.get("soma"),
                 ln.get("pontos"), ln.get("pontos"),
                 (ln["pontos"] >= 12) if ln.get("pontos") is not None else None,
                 ln.get("media") is not None, orig, arquivo))
        except Exception as e:
            db().rollback()
            rejeitados += 1
            erros.append({"linha": i + 2, "motivo": str(e)[:120]})
            continue

    executar("""insert into importacao (arquivo, formato, linhas, criados, atualizados,
                                  rejeitados, usuario_id, evento_id, detalhe)
                values (%s,%s,%s,%s,%s,%s,%s,%s,%s)""",
             (arquivo, d.get("formato", "texto"), len(linhas), criados, atualizados,
              rejeitados, g.usuario["id"], ev["id"], json.dumps(erros[:20])))
    auditar("importar", "maestro", None, None,
            {"arquivo": arquivo, "linhas": len(linhas), "criados": criados},
            "Importação pelo painel", arquivo)
    db().commit()
    return jsonify(ok=True, criados=criados, atualizados=atualizados,
                   rejeitados=rejeitados, erros=erros[:20])


@app.get("/api/admin/importacoes")
@exige(*PAPEIS_ESCRITA)
def admin_importacoes():
    return jsonify(consultar("""
        select i.id, i.arquivo, i.formato, i.linhas, i.criados, i.atualizados,
               i.rejeitados, i.status, i.criado_em, u.nome as usuario, e.nome as evento
          from importacao i
          left join usuario u on u.id = i.usuario_id
          left join evento e on e.id = i.evento_id
         order by i.id desc limit 30"""))


# --------------------------------------------------------------------- estático


@app.get("/")
def raiz():
    return send_from_directory(ESTATICO, "index.html")


@app.get("/<path:arquivo>")
def estatico(arquivo):
    caminho = os.path.join(ESTATICO, arquivo)
    if os.path.isfile(caminho):
        return send_from_directory(ESTATICO, arquivo)
    return send_from_directory(ESTATICO, "index.html")


def autopreparar():
    """Ao subir no servidor, prepara o banco sozinho (tabelas, dados, admin).
    Assim publicar não exige rodar comando no computador de ninguém."""
    try:
        import iniciar
        iniciar.iniciar()
    except Exception as e:
        print("[api] aviso: preparação automática não concluiu:", e, flush=True)


autopreparar()


if __name__ == "__main__":
    porta = int(os.environ.get("PORT", 8000))
    app.run(host="0.0.0.0", port=porta, debug=False)
