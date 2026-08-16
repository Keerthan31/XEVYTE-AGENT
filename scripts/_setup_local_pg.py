"""One-shot local Postgres bootstrap for agents-main (no Docker)."""
from __future__ import annotations

import sys

import psycopg2
from psycopg2 import sql

ROLE = "xevyte_agent"
PASSWORD = "123@Ab"
DB = "xevyte_agent"

# Common local Windows Postgres superuser candidates
CANDIDATES = [
    ("postgres", "postgres"),
    ("postgres", "admin"),
    ("postgres", "password"),
    ("postgres", ""),
    ("postgres", "root"),
]


def try_connect(user: str, password: str):
    kwargs = {
        "host": "127.0.0.1",
        "port": 5432,
        "user": user,
        "dbname": "postgres",
    }
    if password:
        kwargs["password"] = password
    return psycopg2.connect(**kwargs)


def main() -> int:
    conn = None
    used = None
    for user, pwd in CANDIDATES:
        try:
            conn = try_connect(user, pwd)
            used = (user, pwd)
            print(f"Connected as superuser '{user}'")
            break
        except Exception as e:
            print(f"  skip {user}: {e}")

    if conn is None:
        print(
            "\nCould not connect as postgres superuser.\n"
            "Create the role/db manually in pgAdmin or psql:\n"
            f"  CREATE USER {ROLE} WITH PASSWORD '{PASSWORD}';\n"
            f"  CREATE DATABASE {DB} OWNER {ROLE};\n"
            "Then: python -m app.main"
        )
        return 1

    conn.autocommit = True
    cur = conn.cursor()

    cur.execute("SELECT 1 FROM pg_roles WHERE rolname = %s", (ROLE,))
    if cur.fetchone():
        print(f"Role '{ROLE}' already exists")
        cur.execute(sql.SQL("ALTER ROLE {} WITH PASSWORD %s").format(sql.Identifier(ROLE)), (PASSWORD,))
        print(f"Reset password for '{ROLE}'")
    else:
        cur.execute(
            sql.SQL("CREATE ROLE {} WITH LOGIN PASSWORD %s").format(sql.Identifier(ROLE)),
            (PASSWORD,),
        )
        print(f"Created role '{ROLE}'")

    cur.execute("SELECT 1 FROM pg_database WHERE datname = %s", (DB,))
    if cur.fetchone():
        print(f"Database '{DB}' already exists")
    else:
        cur.execute(
            sql.SQL("CREATE DATABASE {} OWNER {}").format(
                sql.Identifier(DB),
                sql.Identifier(ROLE),
            )
        )
        print(f"Created database '{DB}'")

    cur.execute(sql.SQL("GRANT ALL PRIVILEGES ON DATABASE {} TO {}").format(
        sql.Identifier(DB),
        sql.Identifier(ROLE),
    ))
    cur.close()
    conn.close()

    # Verify app credentials work
    try:
        app_conn = psycopg2.connect(
            host="127.0.0.1",
            port=5432,
            user=ROLE,
            password=PASSWORD,
            dbname=DB,
        )
        app_conn.close()
        print(f"Verified login: {ROLE}@{DB}")
    except Exception as e:
        print(f"WARNING: app login failed: {e}")
        return 1

    print("Done. Start the agent with: python -m app.main")
    return 0


if __name__ == "__main__":
    sys.exit(main())
