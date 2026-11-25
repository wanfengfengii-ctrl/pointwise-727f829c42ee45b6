import sqlite3
from contextlib import contextmanager


class StationError(Exception):
    def __init__(self, code, detail=''):
        self.code = code
        self.detail = detail
        super().__init__(f'{code}: {detail}' if detail else code)


def require_text(value, field):
    if not isinstance(value, str) or not value.strip() or '\x00' in value:
        raise StationError('invalid_request', field)
    try:
        value.encode('utf-8')
    except UnicodeError as error:
        raise StationError('invalid_request', field) from error
    return value


def install_source_schema(db):
    db.executescript('''
        CREATE TABLE IF NOT EXISTS recorder (
            singleton INTEGER PRIMARY KEY CHECK (singleton = 1),
            recorder TEXT NOT NULL UNIQUE,
            setting TEXT NOT NULL,
            liters TEXT NOT NULL,
            point INTEGER NOT NULL CHECK (point >= 0),
            cut_sequence INTEGER NOT NULL CHECK (cut_sequence >= 0),
            capacity INTEGER NOT NULL DEFAULT 0 CHECK (capacity >= 0)
        );
        CREATE TABLE IF NOT EXISTS cut_outcomes (
            operation TEXT PRIMARY KEY,
            recorder TEXT NOT NULL REFERENCES recorder(recorder),
            point INTEGER NOT NULL UNIQUE,
            sequence INTEGER NOT NULL UNIQUE CHECK (sequence > 0)
        );
        CREATE TABLE IF NOT EXISTS full_scale_outcomes (
            operation TEXT PRIMARY KEY,
            recorder TEXT NOT NULL REFERENCES recorder(recorder),
            point INTEGER NOT NULL UNIQUE,
            sequence INTEGER NOT NULL UNIQUE CHECK (sequence > 0),
            liters TEXT NOT NULL
        );
        CREATE TABLE IF NOT EXISTS full_scale_bindings (
            boundary_operation TEXT PRIMARY KEY,
            recorder TEXT NOT NULL,
            original_operation TEXT NOT NULL UNIQUE
                REFERENCES full_scale_outcomes(operation),
            point INTEGER NOT NULL,
            sequence INTEGER NOT NULL UNIQUE
        );
    ''')
    columns = {row['name'] for row in db.execute('PRAGMA table_info(recorder)')}
    if 'capacity' not in columns:
        db.execute('ALTER TABLE recorder ADD COLUMN capacity INTEGER NOT NULL DEFAULT 0')


def open_source(path):
    db = sqlite3.connect(path, isolation_level=None)
    db.row_factory = sqlite3.Row
    try:
        db.execute('PRAGMA foreign_keys = ON')
        install_source_schema(db)
    except BaseException:
        db.close()
        raise
    return db


@contextmanager
def source_write(db):
    db.execute('BEGIN IMMEDIATE')
    try:
        yield db
        db.commit()
    except BaseException:
        db.rollback()
        raise
