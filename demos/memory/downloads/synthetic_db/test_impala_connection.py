#!/usr/bin/env python3
"""
Impala connection test script for Cloudera CDP Knox gateway.

Runs a sequence of checks from basic connectivity through live query execution:
  1. TCP / SSL handshake
  2. Authentication
  3. Simple ping query  (SELECT 1)
  4. List databases
  5. List tables in target database
  6. Row-count spot-check on each table
  7. Latency benchmark  (10 × SELECT 1)

Usage:
    python test_impala_connection.py
    python test_impala_connection.py --host <host> --user <user> --password <pwd>

Update USERNAME and PASSWORD (or pass via --user / --password) before running.
"""

import argparse
import sys
import time

# ---------------------------------------------------------------------------
# Connection parameters — update before running
# ---------------------------------------------------------------------------
IMPALA_HOST = 'hue-impala-gateway.datalake.bdqdgc.c0.cloudera.site'
IMPALA_PORT = 443
USERNAME    = 'qishuai'
PASSWORD    = '<workload_pwd>'   # replace with your workload password
DATABASE    = 'banking_chatbot_db'


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------
def ok(msg):   print(f'  \033[32m✓\033[0m  {msg}')
def fail(msg): print(f'  \033[31m✗\033[0m  {msg}')
def info(msg): print(f'     {msg}')
def section(title):
    print(f'\n\033[1m{"─" * 60}\033[0m')
    print(f'\033[1m  {title}\033[0m')
    print(f'\033[1m{"─" * 60}\033[0m')


def connect_impala(host, port, user, password):
    from impala.dbapi import connect
    return connect(
        host=host,
        port=port,
        use_ssl=True,
        use_http_transport=True,
        http_path='cliservice',
        auth_mechanism='PLAIN',
        user=user,
        password=password,
    )


# ---------------------------------------------------------------------------
# Test steps
# ---------------------------------------------------------------------------
def test_import():
    section('1 · Python package')
    try:
        import impala.dbapi          # noqa: F401
        import impala                # noqa: F401
        ok(f'impala package found  (impala=={impala.__version__})')
        return True
    except ImportError as e:
        fail(f'impala package not installed: {e}')
        info('Run:  pip install impyla')
        return False


def test_connect(host, port, user, password):
    section('2 · Connection & authentication')
    info(f'Host : {host}:{port}')
    info(f'User : {user}')
    info(f'SSL  : yes   Transport: HTTP   Auth: PLAIN')
    t0 = time.monotonic()
    try:
        conn = connect_impala(host, port, user, password)
        elapsed = (time.monotonic() - t0) * 1000
        ok(f'Connected  ({elapsed:.0f} ms)')
        return conn
    except Exception as e:
        fail(f'Connection failed: {e}')
        return None


def test_ping(cursor):
    section('3 · Ping  (SELECT 1)')
    try:
        t0 = time.monotonic()
        cursor.execute('SELECT 1')
        row = cursor.fetchone()
        elapsed = (time.monotonic() - t0) * 1000
        if row and row[0] == 1:
            ok(f'SELECT 1 → {row[0]}  ({elapsed:.0f} ms)')
            return True
        else:
            fail(f'Unexpected result: {row}')
            return False
    except Exception as e:
        fail(f'Ping failed: {e}')
        return False


def test_list_databases(cursor):
    section('4 · List databases')
    try:
        cursor.execute('SHOW DATABASES')
        dbs = [r[0] for r in cursor.fetchall()]
        ok(f'{len(dbs)} databases visible')
        for db in sorted(dbs):
            marker = '  ◀ target' if db == DATABASE else ''
            info(f'  {db}{marker}')
        if DATABASE not in dbs:
            fail(f'Target database "{DATABASE}" not found')
            return False
        return True
    except Exception as e:
        fail(f'SHOW DATABASES failed: {e}')
        return False


def test_use_database(cursor):
    section(f'5 · USE {DATABASE}')
    try:
        cursor.execute(f'USE {DATABASE}')
        ok(f'Switched to database: {DATABASE}')
        return True
    except Exception as e:
        fail(f'USE {DATABASE} failed: {e}')
        return False


def test_list_tables(cursor):
    section('6 · List tables')
    try:
        cursor.execute('SHOW TABLES')
        tables = [r[0] for r in cursor.fetchall()]
        ok(f'{len(tables)} tables found')
        for t in sorted(tables):
            info(f'  {t}')
        return tables
    except Exception as e:
        fail(f'SHOW TABLES failed: {e}')
        return []


def test_row_counts(cursor, tables):
    section('7 · Row counts')
    results = {}
    for table in sorted(tables):
        try:
            t0 = time.monotonic()
            cursor.execute(f'SELECT COUNT(*) FROM {table}')
            count = cursor.fetchone()[0]
            elapsed = (time.monotonic() - t0) * 1000
            ok(f'{table:<25} {count:>8,} rows   ({elapsed:.0f} ms)')
            results[table] = count
        except Exception as e:
            fail(f'{table}: {e}')
            results[table] = None
    return results


def test_latency(cursor, iterations=10):
    section(f'8 · Latency benchmark  ({iterations} × SELECT 1)')
    times = []
    for i in range(iterations):
        t0 = time.monotonic()
        try:
            cursor.execute('SELECT 1')
            cursor.fetchone()
            times.append((time.monotonic() - t0) * 1000)
        except Exception as e:
            fail(f'Iteration {i+1} failed: {e}')
    if times:
        avg = sum(times) / len(times)
        mn  = min(times)
        mx  = max(times)
        ok(f'avg {avg:.0f} ms  |  min {mn:.0f} ms  |  max {mx:.0f} ms  |  n={len(times)}')
        if avg < 500:
            info('Latency: GOOD')
        elif avg < 1500:
            info('Latency: ACCEPTABLE')
        else:
            info('Latency: HIGH — consider checking network / gateway load')


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------
def parse_args():
    p = argparse.ArgumentParser(description='Test Impala CDP Knox connection')
    p.add_argument('--host',     default=IMPALA_HOST)
    p.add_argument('--port',     type=int, default=IMPALA_PORT)
    p.add_argument('--user',     default=USERNAME)
    p.add_argument('--password', default=PASSWORD)
    p.add_argument('--database', default=DATABASE)
    return p.parse_args()


def main():
    args = parse_args()

    global DATABASE
    DATABASE = args.database

    print('\n\033[1m' + '═' * 60 + '\033[0m')
    print('\033[1m  Impala Connection Test — Cloudera CDP\033[0m')
    print('\033[1m' + '═' * 60 + '\033[0m')

    # 1. Package
    if not test_import():
        sys.exit(1)

    # 2. Connect
    conn = test_connect(args.host, args.port, args.user, args.password)
    if not conn:
        sys.exit(1)

    cursor = conn.cursor()

    passed = 0
    total  = 6

    # 3–8
    if test_ping(cursor):              passed += 1
    if test_list_databases(cursor):    passed += 1
    if test_use_database(cursor):      passed += 1
    tables = test_list_tables(cursor)
    if tables:                         passed += 1
    if tables:
        counts = test_row_counts(cursor, tables)
        if all(v is not None for v in counts.values()):
            passed += 1
    test_latency(cursor)
    passed += 1   # latency is informational, always counts

    # Summary
    section('Summary')
    colour = '\033[32m' if passed == total else '\033[33m'
    print(f'  {colour}{passed}/{total} checks passed\033[0m')
    if passed < total:
        print('  Review the ✗ entries above for details.')

    cursor.close()
    conn.close()
    print()
    sys.exit(0 if passed == total else 1)


if __name__ == '__main__':
    main()
