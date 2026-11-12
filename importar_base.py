#!/usr/bin/env python3
"""
Carrega a base oficial (rankings 2025/2026/2027 + finais + calendário) no Postgres.

Idempotente: rodar de novo atualiza, não duplica. Usa UPSERT por chave natural:
  animal  -> nome_norm
  pessoa  -> nome_norm
  evento  -> chave
  inscricao -> (evento, categoria, animal)
  resultado -> inscricao

O que a base oficial não traz (profissão, cidade, foto) fica NULL e é
preenchido depois no admin — e nunca é sobrescrito por uma reimportação,
porque o import só escreve nas colunas que ele conhece.
"""
import json
import pathlib
import re
import sys
import unicodedata
import os

RAIZ = pathlib.Path(__file__).resolve().parent
BASE = RAIZ.parent / "portal-freio3" / "src" / "app-1-base.js"


def norm(s):
    s = unicodedata.normalize("NFD", str(s or ""))
    s = "".join(c for c in s if unicodedata.category(c) != "Mn")
    return re.sub(r"\s+", " ", re.sub(r"[^a-z0-9]+", " ", s.lower())).strip()


STOP = {"de", "da", "do", "das", "dos", "e"}


def tokens(s):
    return [x for x in norm(s).split() if x not in STOP and len(x) > 1]


def mesma_pessoa(a, b):
    """Mesma pessoa escrita de formas diferentes.

    O mesmo nome aparece como 'JOAO FRANCISCO FELDMANN VIEIRA' e
    'JOÃO FRACISCO FELDMANN VIEIRA' — sem unificar, cada grafia vira
    uma pessoa e o cavalo parece ter trocado de ginete.

    Cuidado com o contrário: 'JOAO FRANCISCO FELDMANN VIEIRA' e
    'JOAO FRANCISCO MUNOZ DELABARY' compartilham dois prenomes e NÃO são
    a mesma pessoa. Por isso dois nomes comuns só bastam quando o
    sobrenome também aparece nos dois.
    """
    ta, tb = tokens(a), tokens(b)
    if not ta or not tb:
        return False
    seta, setb = set(ta), set(tb)
    comuns = [x for x in ta if x in setb]

    # um nome contido inteiro no outro (nome abreviado ou acrescido)
    menor, maior = (ta, tb) if len(ta) <= len(tb) else (tb, ta)
    if all(x in set(maior) for x in menor):
        return True

    # primeiro nome igual + último nome igual ou abreviado
    if ta[0] == tb[0]:
        u, v = ta[-1], tb[-1]
        if u == v:
            return True
        if len(u) >= 5 and len(v) >= 5 and (u.startswith(v) or v.startswith(u)):
            return True

    # dois ou mais nomes em comum, desde que inclua um sobrenome
    if len(comuns) >= 2 and (ta[-1] in setb or tb[-1] in seta):
        return True

    return False


def ler_base():
    txt = BASE.read_text(encoding="utf-8")
    i = txt.index("const BASE_OFICIAL = ") + len("const BASE_OFICIAL = ")
    return json.loads(txt[i:].rstrip().rstrip(";"))


CATS = [
    ("amador-a", "Amador A", "A", "16 a 40 anos", 1),
    ("master-a", "Master A", "A", "41 a 55 anos", 2),
    ("senior-a", "Sênior A", "A", "56 anos ou mais", 3),
    ("amador-b", "Amador B", "B", "16 a 44 anos", 4),
    ("master-b", "Master B", "B", "45 anos ou mais", 5),
    ("feminina", "Feminina", "B", "16 anos ou mais", 6),
]


def data_iso(s):
    if not s:
        return None
    m = re.match(r"(\d{2})/(\d{2})/(\d{4})", str(s))
    if m:
        return f"{m.group(3)}-{m.group(2)}-{m.group(1)}"
    if re.match(r"\d{4}-\d{2}-\d{2}", str(s)):
        return str(s)[:10]
    return None


class CursorSQL:
    """Cursor falso: em vez de executar, escreve o SQL com os valores.
    Serve para validar a importação contra um Postgres de teste sem depender
    de conexão TCP."""

    def __init__(self, saida):
        self.saida = saida
        self._r = None

    @staticmethod
    def _q(v):
        if v is None:
            return "null"
        if isinstance(v, bool):
            return "true" if v else "false"
        if isinstance(v, (int, float)):
            return str(v)
        return "'" + str(v).replace("'", "''") + "'"

    def execute(self, sql, params=None):
        if params:
            # substituicao posicional simples: cada %s recebe o proximo valor
            partes = sql.split("%s")
            if len(partes) - 1 != len(params):
                raise ValueError(
                    f"{len(partes)-1} marcadores %s para {len(params)} valores")
            sql = "".join(p + self._q(v) for p, v in zip(partes, params)) + partes[-1]
        self.saida.write(sql.strip() + ";\n")
        self._r = (0,)

    def fetchone(self):
        return self._r

    def close(self):
        pass


class ConexaoSQL:
    def __init__(self, caminho):
        self.f = open(caminho, "w", encoding="utf-8")
        self.autocommit = False

    def cursor(self):
        return CursorSQL(self.f)

    def commit(self):
        self.f.flush()

    def rollback(self):
        pass


def main():
    modo_sql = "--sql" in sys.argv

    if modo_sql:
        destino = RAIZ / "tmp_import.sql"
        con = ConexaoSQL(destino)
        cur = con.cursor()
    else:
        import psycopg2
        from psycopg2.extras import execute_values

        url = os.environ.get("DATABASE_URL")
        if not url:
            sys.exit("Defina DATABASE_URL.")
        con = psycopg2.connect(url)
        con.autocommit = False
        cur = con.cursor()
    base = ler_base()

    stats = {"ciclos": 0, "eventos": 0, "animais": 0, "pessoas": 0, "inscricoes": 0, "resultados": 0, "calendario": 0}

    try:
        # ---------------- categorias
        for cat in CATS:
            cur.execute("""
                insert into categoria (id, nome, grupo, idade, ordem)
                values (%s,%s,%s,%s,%s)
                on conflict (id) do update set nome = excluded.nome,
                  grupo = excluded.grupo, idade = excluded.idade, ordem = excluded.ordem
            """, cat)

        # ---------------- ciclos
        for c in base["ciclos"]:
            cur.execute("""
                insert into ciclo (id, nome, disponivel, documento)
                values (%s,%s,%s,%s)
                on conflict (id) do update set
                  nome = excluded.nome,
                  disponivel = excluded.disponivel,
                  documento = excluded.documento,
                  atualizado_em = now()
            """, (c["id"], c["nome"], c.get("disponivel", True), c.get("fonte")))
            stats["ciclos"] += 1

        # ---------------- mapa de animais e pessoas
        animal_id = {}
        pessoa_id = {}

        def garante_animal(nome, extra=None):
            k = norm(nome)
            if k in animal_id:
                return animal_id[k]
            extra = extra or {}
            cur.execute("""
                insert into animal (nome, nome_norm, registro, rg, sexo, pelagem, nascimento,
                                    criador, expositor, estabelecimento, domador, pai_nome, mae_nome,
                                    fonte, selo)
                values (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,'oficial')
                on conflict (nome_norm) do nothing
                returning id
            """, (nome, k, extra.get("registro"), extra.get("rg"), extra.get("sexo"),
                  extra.get("pelagem"), data_iso(extra.get("nascimento")), extra.get("criador"),
                  extra.get("expositor"), extra.get("estabelecimento"), extra.get("domador"),
                  extra.get("pai"), extra.get("mae"), extra.get("fonte") or "catálogo/ranking ABCCC"))
            r = cur.fetchone()
            if r:
                animal_id[k] = r[0]
                stats["animais"] += 1
            else:
                cur.execute("select id from animal where nome_norm = %s", (k,))
                animal_id[k] = cur.fetchone()[0]
            return animal_id[k]

        pessoas_conhecidas = {}   # id -> nome (cache em memória)

        def garante_pessoa(nome):
            k = norm(nome)
            if k in pessoa_id:
                return pessoa_id[k]
            # procura grafia equivalente já cadastrada nesta execução
            for pid, pnome in pessoas_conhecidas.items():
                if mesma_pessoa(nome, pnome):
                    pessoa_id[k] = pid
                    cur.execute(
                        "insert into pessoa_grafia (pessoa_id, grafia) values (%s,%s) "
                        "on conflict do nothing", (pid, nome))
                    return pid
            cur.execute("""
                insert into pessoa (nome, nome_norm, fonte, selo)
                values (%s,%s,'ranking oficial ABCCC','oficial')
                on conflict (nome_norm) do nothing
                returning id
            """, (nome, k))
            r = cur.fetchone()
            if r:
                pessoa_id[k] = r[0]
                stats["pessoas"] += 1
            else:
                cur.execute("select id from pessoa where nome_norm = %s", (k,))
                pessoa_id[k] = cur.fetchone()[0]
            pessoas_conhecidas[pessoa_id[k]] = nome
            return pessoa_id[k]

        # ---------------- eventos de ranking
        ev_ids = {}
        for c in base["ciclos"]:
            if not c.get("disponivel"):
                continue
            chave = "ranking-" + c["id"]
            cur.execute("""
                insert into evento (chave, nome, tipo, ciclo_id, status, documento, fonte, selo, data_inicio)
                values (%s,%s,'ranking',%s,'publicado',%s,'ranking oficial ABCCC','oficial',%s)
                on conflict (chave) do update set
                  nome = excluded.nome, documento = excluded.documento,
                  atualizado_em = now()
                returning id
            """, (chave, "Ranking oficial " + c["nome"], c["id"], c.get("fonte"),
                  {"2025": "2025-08-12", "2026": "2026-09-28", "2027": "2026-11-10"}.get(c["id"])))
            ev_ids[c["id"]] = cur.fetchone()[0]
            stats["eventos"] += 1

        # ---------------- ranking por ciclo
        for ciclo, bloco in base["porCiclo"].items():
            ev = ev_ids.get(ciclo)
            if not ev:
                continue
            nomes_gin = {g["id"]: g["nome"] for g in bloco["ginetes"]}
            nomes_cav = {x["id"]: x["nome"] for x in bloco["cavalos"]}
            for j in bloco["conjuntos"]:
                nome_cav = nomes_cav.get(j["cav"], j["cav"])
                nome_gin = nomes_gin.get(j["gin"], j["gin"])
                aid = garante_animal(nome_cav)
                pid = garante_pessoa(nome_gin)
                cur.execute("""
                    insert into inscricao (evento_id, ciclo_id, categoria_id, animal_id, pessoa_id,
                                           status, fonte, selo)
                    values (%s,%s,%s,%s,%s,%s,%s,'oficial')
                    on conflict (evento_id, categoria_id, animal_id) do update set
                      pessoa_id = excluded.pessoa_id, atualizado_em = now()
                    returning id
                """, (ev, ciclo, j["cat"], aid, pid,
                      "classificado" if j.get("hab") else "participou",
                      "ranking oficial " + ciclo))
                ins = cur.fetchone()[0]
                stats["inscricoes"] += 1
                cur.execute("""
                    insert into resultado (inscricao_id, evento_id, ciclo_id, categoria_id,
                        posicao, posicao_oficial, media, pontos, pontos_oficiais, habilitado,
                        concluiu, origem, fonte, selo)
                    values (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,'credenciadora',%s,'oficial')
                    on conflict (inscricao_id) do update set
                      posicao = excluded.posicao, posicao_oficial = excluded.posicao_oficial,
                      media = excluded.media, pontos = excluded.pontos,
                      habilitado = excluded.habilitado, atualizado_em = now()
                """, (ins, ev, ciclo, j["cat"], j["pos"], j["pos"], j.get("nota"),
                      j.get("pts"), j.get("pts"), j.get("hab"),
                      j.get("nota") is not None, "ranking oficial " + ciclo))
                stats["resultados"] += 1

        # ---------------- final 2026 (catálogo + súmula)
        f = base["final2026"]
        cur.execute("""
            insert into evento (chave, nome, tipo, ciclo_id, cidade, uf, local, data_inicio, data_fim,
                                status, documento, fonte, selo)
            values ('final-2026',%s,'final','2026','Esteio','RS',%s,'2026-10-12','2026-10-17',
                    'publicado',%s,'catálogo oficial da Final','oficial')
            on conflict (chave) do update set
              nome = excluded.nome, documento = excluded.documento, atualizado_em = now()
            returning id
        """, (f["nome"], f["local"], f["catalogo"]))
        ev_final = cur.fetchone()[0]
        stats["eventos"] += 1

        cur.execute("""
            insert into final (ciclo_id, nome, local, data_inicio, data_fim,
                               conjuntos_inscritos, tem_classificacao, documento)
            values ('2026',%s,%s,'2026-10-12','2026-10-17',%s,%s,%s)
            on conflict (ciclo_id) do update set
              conjuntos_inscritos = excluded.conjuntos_inscritos,
              tem_classificacao = excluded.tem_classificacao,
              documento = excluded.documento, atualizado_em = now()
        """, (f["nome"], f["local"], f["conjuntosInscritos"],
              bool(f.get("sumulaCompleta")), f["catalogo"]))

        # inscrições do catálogo
        ins_final = {}
        for fc in f["conjuntos"]:
            aid = garante_animal(fc["cavalo"], fc)
            pid = garante_pessoa(fc["ginete"])
            cur.execute("""
                insert into inscricao (evento_id, ciclo_id, categoria_id, animal_id, pessoa_id,
                                       box, status, fonte, selo)
                values (%s,'2026',%s,%s,%s,%s,'inscrito',%s,'oficial')
                on conflict (evento_id, categoria_id, animal_id) do update set
                  pessoa_id = excluded.pessoa_id, box = excluded.box, atualizado_em = now()
                returning id
            """, (ev_final, fc["cat"], aid, pid, fc.get("box"), "catálogo da Final 2026"))
            ins_final[(fc["cat"], fc.get("box"))] = cur.fetchone()[0]
            stats["inscricoes"] += 1

        # posições e notas da súmula completa
        for s in f.get("sumulaCompleta", []) or []:
            ins = ins_final.get((s["categoria"], s.get("box")))
            if not ins:
                continue
            cur.execute("""
                insert into resultado (inscricao_id, evento_id, ciclo_id, categoria_id,
                    posicao, posicao_oficial, media, concluiu, origem, fonte, selo)
                values (%s,%s,'2026',%s,%s,%s,%s,%s,'final','súmula oficial da Final','oficial')
                on conflict (inscricao_id) do update set
                  posicao = excluded.posicao, posicao_oficial = excluded.posicao_oficial,
                  media = excluded.media, concluiu = excluded.concluiu, atualizado_em = now()
            """, (ins, ev_final, s["categoria"], s.get("posicao"), s.get("posicao"),
                  s.get("mediaFinal"), s.get("mediaFinal") is not None))
            stats["resultados"] += 1

        # finais 2024/2025 (só pódio)
        for ano, fx in (base.get("finais") or {}).items():
            cur.execute("""
                insert into ciclo (id, nome, disponivel, documento) values (%s,%s,true,%s)
                on conflict (id) do update set documento = excluded.documento
            """, (ano, "Ciclo " + ano, fx.get("resultados")))
            cur.execute("""
                insert into evento (chave, nome, tipo, ciclo_id, cidade, uf, local,
                                    data_inicio, data_fim, status, documento, fonte, selo)
                values (%s,%s,'final',%s,'Esteio','RS',%s,%s,%s,'publicado',%s,'notícia oficial ABCCC','oficial')
                on conflict (chave) do update set nome = excluded.nome, atualizado_em = now()
                returning id
            """, ("final-" + ano, fx["nome"], ano, fx["local"],
                  {"2024": "2024-09-25", "2025": "2025-10-13"}[ano],
                  {"2024": "2024-09-28", "2025": "2025-10-18"}[ano],
                  fx.get("resultados")))
            ev = cur.fetchone()[0]
            stats["eventos"] += 1
            for p in fx.get("podium", []):
                aid = garante_animal(p["cavalo"])
                pid = garante_pessoa(p["ginete"])
                cur.execute("""
                    insert into inscricao (evento_id, ciclo_id, categoria_id, animal_id, pessoa_id,
                                           box, status, fonte, selo)
                    values (%s,%s,%s,%s,%s,%s,'finalista',%s,'oficial')
                    on conflict (evento_id, categoria_id, animal_id) do update set
                      pessoa_id = excluded.pessoa_id, atualizado_em = now()
                    returning id
                """, (ev, ano, p["categoria"], aid, pid, p.get("box"), "notícia oficial " + ano))
                ins = cur.fetchone()[0]
                cur.execute("""
                    insert into resultado (inscricao_id, evento_id, ciclo_id, categoria_id,
                        posicao, posicao_oficial, media, concluiu, origem, fonte, selo)
                    values (%s,%s,%s,%s,%s,%s,%s,%s,'final',%s,'oficial')
                    on conflict (inscricao_id) do update set
                      posicao = excluded.posicao, media = excluded.media, atualizado_em = now()
                """, (ins, ev, ano, p["categoria"], p["posicao"], p["posicao"],
                      p.get("nota"), p.get("nota") is not None, "notícia oficial " + ano))
                stats["inscricoes"] += 1
                stats["resultados"] += 1

        # ---------------- calendário
        for c in base.get("calendario", []):
            cur.execute("""
                insert into calendario_prova (cidade, data, tipo, ciclo_id, fonte)
                values (%s,%s,'credenciadora',%s,'calendário ABCCC')
                on conflict (cidade, data) do nothing
            """, (c["cidade"], c["data"], "2027" if c["data"] >= "2026-10-17" else "2026"))
            stats["calendario"] += 1

        con.commit()
        if modo_sql:
            con.f.close()
            print(f"SQL gerado em {destino}")
            for k, v in stats.items():
                print(f"  {k:12} {v}")
            return
        print("Importação concluída:")
        for k, v in stats.items():
            print(f"  {k:12} {v}")

    except Exception as e:
        con.rollback()
        print("FALHOU — nada foi gravado (transação desfeita).")
        print(e)
        raise


if __name__ == "__main__":
    main()
