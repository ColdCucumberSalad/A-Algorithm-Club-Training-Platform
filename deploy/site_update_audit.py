"""Run inside an app image: compare all existing table values across migrations."""
import hashlib
import json
import os
from pathlib import Path
import sys
import psycopg
from psycopg import sql


def audit(mode):
    path = Path('/audit/data-before.json')
    previous = json.loads(path.read_text()) if mode == 'verify' else None
    result = {}
    with psycopg.connect(dbname=os.environ['POSTGRES_DB'], user=os.environ['POSTGRES_USER'],
                         password=os.environ['POSTGRES_PASSWORD'], host=os.environ.get('POSTGRES_HOST', 'db'),
                         port=os.environ.get('POSTGRES_PORT', '5432')) as connection:
        with connection.cursor() as cursor:
            cursor.execute("SELECT tablename FROM pg_tables WHERE schemaname='public' ORDER BY tablename")
            tables = [row[0] for row in cursor.fetchall() if row[0] not in ('django_migrations', 'auth_permission', 'django_content_type')]
            for table in previous if previous is not None else tables:
                if previous is not None:
                    columns = previous[table]['columns']
                else:
                    cursor.execute("SELECT column_name FROM information_schema.columns WHERE table_schema='public' AND table_name=%s ORDER BY ordinal_position", [table])
                    columns = [row[0] for row in cursor.fetchall()]
                query = sql.SQL('SELECT row_to_json(v)::text FROM (SELECT {} FROM {}) v ORDER BY row_to_json(v)::text').format(
                    sql.SQL(',').join(map(sql.Identifier, columns)), sql.Identifier(table))
                digest, count = hashlib.sha256(), 0
                with connection.cursor(name='data_audit') as stream:
                    stream.execute(query)
                    for row in stream:
                        digest.update(row[0].encode()); digest.update(b'\n'); count += 1
                result[table] = {'columns': columns, 'count': count, 'sha256': digest.hexdigest()}
    if previous is None:
        path.write_text(json.dumps(result))
    else:
        differences = [table for table in previous if previous[table] != result[table]]
        print(json.dumps({'checked_tables': len(previous), 'rows': sum(row['count'] for row in result.values()), 'differences': differences}))
        if differences:
            raise RuntimeError('原有数据发生变化，更新需要人工审查')


if __name__ == '__main__':
    if sys.argv[1] not in ('capture', 'verify'):
        raise ValueError('Invalid audit mode')
    audit(sys.argv[1])
