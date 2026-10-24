"""AgentBench DB: real MySQL, upstream initialization and result processor."""
from __future__ import annotations
import ast
import asyncio
from contextlib import contextmanager, redirect_stdout
from functools import lru_cache
import hashlib
import importlib.util
import io
import json
from pathlib import Path
import secrets
import sys
import types
import typing
from evaluation_datasets import _support

ROOT = Path(__file__).resolve().parent
CONNECTION = ROOT / '.runtime/connection.json'
LIMIT = 50
COMMITTED = 'Final answer recorded.'


@lru_cache(maxsize=1)
def activate():
    _support.activate(ROOT, 'vendor')
    source = ROOT / 'vendor/src/server/tasks/dbbench'
    # interaction.Database is only a typing import. Avoid importing the unrelated
    # AgentRL/Redis orchestration stack; execute the original result processor.
    prefix = '_sage_official_dbbench'
    package = types.ModuleType(prefix)
    package.__path__ = [str(source)]
    sys.modules[prefix] = package
    interaction = types.ModuleType(prefix + '.interaction')
    interaction.Database = object
    sys.modules[interaction.__name__] = interaction
    spec = importlib.util.spec_from_file_location(prefix + '.result_processor', source / 'result_processor.py')
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    tree = ast.parse((source / 'task.py').read_text())
    method = next(n for n in ast.walk(tree) if isinstance(n, ast.FunctionDef) and n.name == '_build_init_sql')
    method.decorator_list = []
    namespace = vars(typing).copy()
    exec(compile(ast.Module(body=[method], type_ignores=[]), str(source / 'task.py'), 'exec'), namespace)
    return module.DBResultProcessor, namespace['_build_init_sql']


@lru_cache(maxsize=1)
def tasks():
    return {'agentbench-db-' + str(i): t for i, t in enumerate(
        json.loads(line) for line in (ROOT / 'vendor/data/dbbench/standard.jsonl').read_text().splitlines() if line)}


def task(context):
    return tasks()[context['task_id']]


def tools(context=None):
    return [{'name': 'execute_sql', 'description': 'Execute one MySQL statement in this task database; results are truncated at 800 characters.',
        'parameters': {'type': 'object', 'properties': {'query': {'type': 'string', 'minLength': 1, 'maxLength': 20000}}, 'required': ['query'], 'additionalProperties': False}},
        {'name': 'commit_final_answer', 'description': 'Submit the final answer once and end the episode. For modification tasks, actual table contents determine success.',
        'parameters': {'type': 'object', 'properties': {'answers': {'type': 'array', 'items': {'type': 'string'}, 'maxItems': 1000}}, 'required': ['answers'], 'additionalProperties': False}}]


def validate(name, args):
    if name == 'execute_sql' and set(args) == {'query'} and isinstance(args['query'], str) and 0 < len(args['query']) <= 20000:
        return
    if name == 'commit_final_answer' and set(args) == {'answers'} and isinstance(args['answers'], list) and len(args['answers']) <= 1000 and all(isinstance(a, str) for a in args['answers']):
        return
    raise ValueError('Invalid DB tool arguments')


def initial(context):
    task(context)
    return {'queries': [], 'answers': None}


def configuration():
    if not CONNECTION.is_file():
        raise RuntimeError('Managed MySQL is not configured. Install Docker and run: python -m evaluation_datasets.agentbench_db.manage start')
    config = json.loads(CONNECTION.read_text())
    if config.get('host') != '127.0.0.1' or not config.get('container_id'):
        raise ValueError('Only the managed local MySQL container is supported')
    return config


def connect(config, *, user='root', password=None, database=None):
    import mysql.connector
    return mysql.connector.connect(host='127.0.0.1', port=config['port'], user=user,
        password=config['password'] if password is None else password, database=database,
        charset='utf8mb4', autocommit=False, connection_timeout=5, read_timeout=60, write_timeout=10,
        allow_local_infile=False)


@contextmanager
def database(context):
    # Stable names make native metadata-query observations replayable. Serialize
    # reconstruction across processes, then grant only this fresh database.
    from filelock import FileLock
    config = configuration()
    with FileLock(str(ROOT / '.runtime/replay.lock'), timeout=120):
        admin = connect(config)
        name = 'sage_' + hashlib.sha256(context['task_id'].encode()).hexdigest()[:20]
        user = 'rsi_' + secrets.token_hex(8)
        password = secrets.token_hex(24)
        conn = None
        try:
            with admin.cursor() as c:
                c.execute(f'CREATE DATABASE `{name}`')
                c.execute("CREATE USER %s@%s IDENTIFIED BY %s", (user, '%', password))
                c.execute(f"GRANT ALL PRIVILEGES ON `{name}`.* TO '{user}'@'%'")
            conn = connect(config, user=user, password=password, database=name)
            _, initializer = activate()
            with conn.cursor() as c:
                c.execute('SET SESSION MAX_EXECUTION_TIME=10000')
                for item in initializer(task(context)):
                    c.execute(item) if isinstance(item, str) else c.execute(*item)
            conn.commit()
            yield conn
        finally:
            if conn is not None:
                conn.close()
            with admin.cursor() as c:
                c.execute(f'DROP DATABASE IF EXISTS `{name}`')
                c.execute(f"DROP USER IF EXISTS '{user}'@'%'")
            admin.close()


def execute(conn, query):
    import mysql.connector
    try:
        with conn.cursor() as c:
            c.execute(query)
            result = str(list(c.fetchall())) if c.with_rows else '[]'
        conn.commit()
    except mysql.connector.Error as e:
        if e.errno in (2002, 2003, 2006, 2013, 2055):
            raise
        conn.rollback()
        result = str(e)
    return result[:800] + '[TRUNCATED]' if len(result) > 800 else result


def replay(context, queries, *, table_hash=False):
    if len(queries) > LIMIT:
        raise ValueError('DB SQL statement budget exceeded (50)')
    processor, _ = activate()
    with database(context) as conn:
        results = [execute(conn, query) for query in queries]
        value = None
        if table_hash:
            class OfficialConnection:
                async def execute(self, sql):
                    return execute(conn, sql)
            value = asyncio.run(processor.calculate_tables_hash_async(OfficialConnection(), task(context)))
    return results, value


def call(context, state, name, args):
    validate(name, args)
    if state['answers'] is not None:
        raise ValueError('The final answer was already committed')
    state = {'queries': list(state['queries']), 'answers': None}
    if name == 'execute_sql':
        state['queries'].append(args['query'])
        results, _ = replay(context, state['queries'])
        return state, results[-1], False
    state['answers'] = args['answers']
    return state, COMMITTED, False


def compare(answer, expected, kind):
    processor, _ = activate()
    # Passing a list to the upstream cleaner bypasses its unsafe string eval.
    # Labels come only from pinned upstream files; model answers are list[str].
    with redirect_stdout(io.StringIO()):
        return processor.compare_results(answer, expected, kind)


def evaluate(context, queries, answers, expected_results):
    entry = task(context)
    if answers is None:
        return False
    kind = entry['type'][0]
    writes = kind in ('INSERT', 'UPDATE', 'DELETE')
    if queries or writes:
        results, actual_hash = replay(context, queries, table_hash=writes)
        if results != expected_results:
            raise ValueError('Native SQL results differ from MySQL replay')
    if writes:
        expected_hash = entry.get('answer_md5', '')
        if expected_hash == '':
            _, expected_hash = replay(context, [entry['sql']['query']], table_hash=True)
        return compare([actual_hash], [expected_hash], kind)
    return compare(answers, entry['label'], kind)


def preflight():
    activate()
    config = configuration()
    with connect(config) as conn:
        with conn.cursor() as c:
            c.execute('SELECT VERSION()')
            version = c.fetchone()[0]
    # Verify real task creation, permissions, SQL and cleanup as well as connectivity.
    replay({'task_id': next(iter(tasks()))}, ['SHOW TABLES'])
    return {'ready': True, 'tasks': len(tasks()), 'mysql_version': version}


if __name__ == '__main__':
    print(json.dumps(preflight()))
