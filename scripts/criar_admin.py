#!/usr/bin/env python3
"""Cria ou redefine a senha de um usuário administrador."""
import os, secrets, sys
from hashlib import pbkdf2_hmac
import psycopg2


def hash_senha(s):
    sal = secrets.token_hex(16)
    return f"pbkdf2${sal}${pbkdf2_hmac('sha256', s.encode(), sal.encode(), 200000).hex()}"


if __name__ == "__main__":
    if len(sys.argv) < 4:
        sys.exit("uso: python3 scripts/criar_admin.py nome email senha")
    nome, email, senha = sys.argv[1], sys.argv[2], sys.argv[3]
    con = psycopg2.connect(os.environ["DATABASE_URL"])
    con.autocommit = True
    with con.cursor() as cur:
        cur.execute("""
            insert into usuario (nome, email, senha_hash, papel)
            values (%s,%s,%s,'superadmin')
            on conflict (lower(email)) do update set
              senha_hash = excluded.senha_hash, ativo = true, papel = 'superadmin'
        """, (nome, email.lower(), hash_senha(senha)))
    print("administrador pronto:", email)
