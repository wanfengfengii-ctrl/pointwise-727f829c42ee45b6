import sqlite3
from contextlib import contextmanager
from pathlib import Path

from source.store import StationError as StationError


def open_business(path, *, must_exist=False):
    target = Path(path).resolve().as_uri() + '?mode=rw' if must_exist else path
    db = sqlite3.connect(target, uri=must_exist, isolation_level=None)
    db.row_factory = sqlite3.Row
    try:
        db.execute('PRAGMA foreign_keys = ON')
    except BaseException:
        db.close()
        raise
    return db


@contextmanager
def _transaction(db, begin):
    db.execute(begin)
    try:
        yield db
        db.commit()
    except BaseException:
        db.rollback()
        raise


def business_write(db):
    return _transaction(db, 'BEGIN IMMEDIATE')


def business_read(db):
    return _transaction(db, 'BEGIN')
