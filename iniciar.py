#!/usr/bin/env python3
"""
Inicialização automática do banco.

Existe para que publicar não exija rodar comando nenhum no seu computador:
o próprio app, ao subir, verifica se o banco está vazio e, se estiver,
cria as tabelas, aplica as views e carrega a base oficial.

Variáveis de ambiente:
  AUTO_INICIAR=1            liga (padrão: ligado)
  ADMIN_EMAIL=...           e-mail do administrador criado no primeiro boot
  ADMIN_SENHA=...           senha inicial desse administrador
  ADMIN_NOME=...            nome exibido

Tudo é idempotente: rodar de novo não recria, não duplica e não apaga.
"""
import os
import secrets
import unicodedata
import re
import sys
from hashlib import pbkdf2_hmac

RAIZ = os.path.dirname(os.path.abspath(__file__))
DB = os.path.join(RAIZ, "db")


def log(msg):
    print(f"[inicio] {msg}", flush=True)


def hash_senha(s):
    sal = secrets.token_hex(16)
    return f"pbkdf2${sal}${pbkdf2_hmac('sha256', s.encode(), sal.encode(), 200000).hex()}"


def conectar():
    import psycopg2
    url = os.environ.get("DATABASE_URL")
    if not url:
        raise RuntimeError("DATABASE_URL não definida")
    con = psycopg2.connect(url)
    con.autocommit = False
    return con


def versao_atual(con):
    with con.cursor() as cur:
        cur.execute("""
            select exists (select 1 from information_schema.tables
              where table_schema='public' and table_name='schema_version')""")
        if not cur.fetchone()[0]:
            return 0
        cur.execute("select coalesce(max(versao),0) from schema_version")
        return cur.fetchone()[0]


# Trava de aviso do PostgreSQL: um número fixo que só uma sessão segura por vez.
# O gunicorn sobe 2 workers e cada um executa esta preparação no boot; sem a
# trava, os dois leriam "versão 2" e aplicariam a mesma migração ao mesmo tempo
# (create table if not exists NÃO é seguro em execução simultânea).
TRAVA_MIGRACAO = 728193465


def aplica_migracoes(con):
    """Aplica os .sql de db/ em ordem. Cada um roda uma vez, e um por vez."""
    with con.cursor() as cur:
        cur.execute("select pg_advisory_lock(%s)", (TRAVA_MIGRACAO,))
    try:
        arquivos = sorted(f for f in os.listdir(DB) if f.endswith(".sql"))
        # relê DENTRO da trava: o outro worker pode ter acabado de aplicar
        aplicadas = versao_atual(con)
        for arq in arquivos:
            n = int(re.match(r"(\d+)", arq).group(1))
            if n <= aplicadas:
                continue
            log(f"aplicando migração {arq}")
            sql = open(os.path.join(DB, arq), encoding="utf-8").read()
            with con.cursor() as cur:
                cur.execute(sql)
                cur.execute("""
                    insert into schema_version (versao, arquivo)
                    values (%s,%s) on conflict (versao) do nothing""", (n, arq))
            con.commit()
    finally:
        try:
            with con.cursor() as cur:
                cur.execute("select pg_advisory_unlock(%s)", (TRAVA_MIGRACAO,))
        except Exception:
            pass


def base_vazia(con):
    with con.cursor() as cur:
        cur.execute("select count(*) from animal")
        return cur.fetchone()[0] == 0


def importa_base():
    """Chama o importador (ele abre a própria conexão)."""
    log("carregando a base oficial (rankings, finais e calendário)")
    sys.path.insert(0, RAIZ)
    import importar_base
    importar_base.main()


def garante_admin(con):
    email = os.environ.get("ADMIN_EMAIL")
    senha = os.environ.get("ADMIN_SENHA")
    nome = os.environ.get("ADMIN_NOME", "Administrador")
    with con.cursor() as cur:
        cur.execute("select count(*) from usuario where papel in ('admin','superadmin')")
        if cur.fetchone()[0] > 0:
            return
    if not email or not senha:
        log("NENHUM ADMINISTRADOR DEFINIDO. Defina ADMIN_EMAIL e ADMIN_SENHA "
            "nas variáveis do serviço e reinicie.")
        return
    with con.cursor() as cur:
        cur.execute("""
            insert into usuario (nome, email, senha_hash, papel)
            values (%s,%s,%s,'superadmin')
            on conflict (lower(email)) do update set senha_hash = excluded.senha_hash""",
            (nome, email.lower(), hash_senha(senha)))
    con.commit()
    log(f"administrador criado: {email}")


def garante_banners(con):
    """Banners de demonstração, só se não houver nenhum."""
    with con.cursor() as cur:
        cur.execute("select count(*) from banner")
        if cur.fetchone()[0] > 0:
            return
        cur.execute("""
            insert into banner (titulo, texto, cor, posicao, ativo) values
              ('Cabanha Santa Lívia','Reprodutores de origem','#2f5d43','topo',true),
              ('Leilão Reconquista','Genética provada em pista','#8a5a2b','topo',true),
              ('Vetnil','Saúde e nutrição animal','#2a4a6b','listas',true),
              ('Anuncie aqui','Seu produto para criadores de todo o Brasil',
               '#5c5346','rodape',true)""")
    con.commit()
    log("banners de demonstração criados")


def iniciar():
    if os.environ.get("AUTO_INICIAR", "1") not in ("1", "true", "True", "sim"):
        return
    try:
        con = conectar()
    except Exception as e:
        log(f"banco indisponível ainda: {e}")
        return
    try:
        aplica_migracoes(con)
        precisa_importar = base_vazia(con)
        # fecha antes de abrir a conexão do importador: nunca manter duas
        # conexões abertas ao mesmo tempo (o importador abre a própria)
        con.close()
        con = None
        if precisa_importar:
            importa_base()
        con = conectar()
        garante_admin(con)
        garante_banners(con)
        log("banco pronto")
    except Exception as e:
        log(f"falhou a preparação: {e}")
        raise
    finally:
        if con is not None:
            try:
                con.close()
            except Exception:
                pass


if __name__ == "__main__":
    iniciar()
