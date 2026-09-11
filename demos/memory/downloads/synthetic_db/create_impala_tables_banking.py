#!/usr/bin/env python3
"""
Create digital banking chatbot tables in Impala (Cloudera Data Warehouse).

Creates six tables in the banking_chatbot_db database:
  - customers      : Customer identity and KYC registry
  - accounts       : Bank accounts (checking, savings, money market, CD)
  - transactions   : Full transaction history with status and failure reasons
  - loans          : Active and historical loan accounts
  - cards          : Debit and credit cards linked to accounts
  - support_cases  : Open and historical support cases

The schema is defined once in create_tables_impala.sql; this script reads that
file and executes only its DDL statements (CREATE DATABASE / USE / DROP TABLE /
CREATE TABLE), skipping the LOAD DATA and example SELECT statements. Data loading
is handled separately by load_data_to_impala_banking.py.

Usage:
    python create_impala_tables_banking.py

Update IMPALA_HOST, USERNAME, and PASSWORD before running.
"""

import sys
from pathlib import Path

from impala.dbapi import connect

# ---------------------------------------------------------------------------
# Connection parameters — update for your CDP environment
# ---------------------------------------------------------------------------
IMPALA_HOST   = 'hue-impala-gateway.datalake.bdqdgc.c0.cloudera.site'
IMPALA_PORT   = 443
USERNAME      = 'qishuai'
PASSWORD      = '<workload_pwd>'   # replace with your workload password
DATABASE      = 'banking_chatbot_db'

# ---------------------------------------------------------------------------
# DDL source — schema lives in the .sql file (single source of truth)
# ---------------------------------------------------------------------------
DDL_FILE = Path(__file__).parent / "create_tables_impala.sql"
DDL_PREFIXES = ("CREATE DATABASE", "USE ", "DROP TABLE", "CREATE TABLE")

VERIFY_TABLES = [
    "customers",
    "accounts",
    "transactions",
    "loans",
    "cards",
    "support_cases",
]


def load_ddl_statements(path: Path) -> list:
    """Return only the DDL statements from the .sql file.

    Full-line ``--`` comments are dropped, statements are split on ``;`` (the
    COMMENT clauses contain no semicolons), and only statements beginning with a
    DDL keyword are kept — LOAD DATA and example SELECT queries are skipped.
    """
    lines = [
        line for line in path.read_text(encoding="utf-8").splitlines()
        if not line.strip().startswith("--")
    ]
    statements = []
    for raw in "\n".join(lines).split(";"):
        stmt = raw.strip()
        if stmt and stmt.upper().startswith(DDL_PREFIXES):
            statements.append(stmt)
    return statements


# ---------------------------------------------------------------------------
# Connection helper
# ---------------------------------------------------------------------------
def connect_to_impala():
    """Connect to Impala via CDP gateway using PLAIN/LDAP workload credentials."""
    try:
        print(f"  Connecting to {IMPALA_HOST}:{IMPALA_PORT}...")
        conn = connect(
            host=IMPALA_HOST,
            port=IMPALA_PORT,
            use_ssl=True,
            use_http_transport=True,
            http_path='cliservice',
            auth_mechanism='PLAIN',
            user=USERNAME,
            password=PASSWORD,
        )
        cursor = conn.cursor()
        cursor.execute("SELECT 1")
        print(f"  Connected.\n")
        return conn, cursor
    except Exception as e:
        print(f"  Connection failed: {e}")
        return None, None


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------
def main():
    print("=" * 70)
    print("Banking Chatbot DB — Create Tables")
    print("=" * 70)
    print(f"Host    : {IMPALA_HOST}:{IMPALA_PORT}")
    print(f"User    : {USERNAME}")
    print(f"Database: {DATABASE}\n")

    statements = load_ddl_statements(DDL_FILE)
    print(f"Loaded {len(statements)} DDL statements from {DDL_FILE.name}\n")

    conn, cursor = connect_to_impala()
    if not conn:
        print("\n✗ All connection attempts failed. Check host/credentials.")
        sys.exit(1)

    try:
        for sql in statements:
            label = sql.splitlines()[0].strip()
            print(f"{label} ...")
            cursor.execute(sql)
            print(f"  ✓ Done\n")

        print("=" * 70)
        print("Table verification")
        print("=" * 70)
        for table in VERIFY_TABLES:
            cursor.execute(f"DESCRIBE {table}")
            columns = cursor.fetchall()
            print(f"\n{table}")
            print("-" * 60)
            for col in columns:
                name    = col[0]
                dtype   = col[1]
                comment = col[2] if len(col) > 2 else ''
                print(f"  {name:<28} {dtype:<16} {comment}")
            print(f"  ({len(columns)} columns)")

        print("\n✓ All tables created successfully.")
        print(f"\nNext step: run  load_data_to_impala_banking.py  to populate the tables.")

    except Exception as e:
        print(f"\n✗ Error: {e}")
        import traceback
        traceback.print_exc()
        sys.exit(1)
    finally:
        cursor.close()
        conn.close()


if __name__ == "__main__":
    main()
