#!/usr/bin/env python3
"""
Migrador do Portal Freio.

Regra que protege o banco legado:
  - Cada arquivo em db/ roda UMA vez, na ordem numérica, dentro de uma transação.
  - O banco guarda em schema_version o que já rodou.
  - Migração nova só ACRESCENTA. Nunca altera coluna existente.
  - `--seco` mostra o que rodaria sem tocar em nada.
  - `--backup` grava um dump antes de aplicar.

Uso:
  python3 migrate.py                 # aplica o que falta
  python3 migrate.py --seco          # só lista
  python3 migrate.py --backup        # dump antes de aplicar
"""
import argparse
import hashlib
import json
import os
import pathlib
import re
import subprocess
import sys
from datetime import datetime

RAIZ = pathlib.Path(__file__).resolve().parent
DB = RAIZ / "db"


def conexao():
    """Postgres puro. Não usa nada exclusivo de Supabase/Neon/Railway."""
    url = os.environ.get("DATABASE_URL")
    if not url:
        sys.exit(
            "Defina DATABASE_URL, por exemplo:\n"
            "  export DATABASE_URL='postgresql://usuario:senha@host:5432/banco'"
        )
    import psycopg2
    return psycopg2.connect(url)


def arquivos():
    return sorted(DB.glob("*.sql"), key=lambda p: int(re.match(r"(\d+)", p.name).group(1)))


def ja_aplicadas(con):
    with con.cursor() as cur:
        cur.execute("""
            select exists (
              select 1 from information_schema.tables
              where table_schema = 'public' and table_name = 'schema_version'
            )
        """)
        if not cur.fetchone()[0]:
            return set()
        cur.execute("select versao from schema_version")
        return {r[0] for r in cur.fetchall()}


def registrar(con, numero, nome, checksum):
    with con.cursor() as cur:
        cur.execute(
            "insert into schema_version (versao, arquivo, checksum) values (%s,%s,%s)",
            (numero, nome, checksum),
        )


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--seco", action="store_true", help="só mostra o que rodaria")
    ap.add_argument("--backup", action="store_true", help="pg_dump antes de aplicar")
    a = ap.parse_args()

    con = conexao()
    aplicadas = ja_aplicadas(con)
    pendentes = [(int(re.match(r"(\d+)", p.name).group(1)), p) for p in arquivos()]
    pendentes = [(n, p) for n, p in pendentes if n not in aplicadas]

    if not pendentes:
        print("Banco já está na última versão. Nada a fazer.")
        return

    print(f"{len(pendentes)} migração(ões) pendente(s):")
    for n, p in pendentes:
        print(f"  {p.name}")

    if a.seco:
        print("\n(modo seco: nada foi alterado)")
        return

    if a.backup:
        alvo = RAIZ / "backups" / datetime.now().strftime("%Y%m%d-%H%M%S") + ".sql"
        alvo.parent.mkdir(exist_ok=True)
        with open(alvo, "w") as f:
            subprocess.run(["pg_dump", os.environ["DATABASE_URL"]], stdout=f, check=True)
        print(f"backup salvo em {alvo}")

    for n, p in pendentes:
        sql = p.read_text(encoding="utf-8")
        checksum = hashlib.sha256(sql.encode()).hexdigest()[:16]
        print(f"aplicando {p.name} …", end=" ", flush=True)
        try:
            with con.cursor() as cur:
                cur.execute(sql)
                if n >= 3:
                    cur.execute(
                        "insert into schema_version (versao, arquivo, checksum) values (%s,%s,%s)",
                        (n, p.name, checksum),
                    )
            if n < 3:
                # a 001 cria a própria schema_version; registra as duas depois
                with con.cursor() as cur:
                    for nn, pp in pendentes:
                        if nn <= n:
                            cur.execute(
                                "insert into schema_version (versao, arquivo, checksum) "
                                "values (%s,%s,%s) on conflict do nothing",
                                (nn, pp.name, checksum),
                            )
            con.commit()
            print("ok")
        except Exception as e:
            con.rollback()
            print("FALHOU")
            print(f"\n{e}")
            print("\nNada foi gravado: a transação foi desfeita.")
            sys.exit(1)

    print("\nBanco atualizado.")


if __name__ == "__main__":
    main()
