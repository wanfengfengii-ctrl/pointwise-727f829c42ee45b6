from dataclasses import dataclass

from source.store import StationError, require_text, source_write


@dataclass(frozen=True)
class DeviceConfig:
    recorder: str
    setting: str


def read_registration(db, recorder):
    require_text(recorder, 'recorder')
    row = db.execute(
        'SELECT recorder, setting, capacity FROM recorder WHERE recorder = ?', (recorder,)
    ).fetchone()
    if row is None:
        raise StationError('unknown_recorder', recorder)
    return DeviceConfig(row['recorder'], row['setting'])


def read_capacity(db, recorder):
    read_registration(db, recorder)
    return db.execute('SELECT capacity FROM recorder WHERE recorder = ?', (recorder,)).fetchone()[0]


def configure(db, recorder, setting):
    config = DeviceConfig(require_text(recorder, 'recorder'), require_text(setting, 'setting'))
    with source_write(db):
        row = db.execute('SELECT recorder, setting FROM recorder WHERE singleton = 1').fetchone()
        if row is None:
            db.execute(
                'INSERT INTO recorder (singleton, recorder, setting, liters, point, cut_sequence) '
                'VALUES (1, ?, ?, ?, 0, 0)',
                (config.recorder, config.setting, '0'),
            )
            return config
        original = DeviceConfig(row['recorder'], row['setting'])
        if original != config:
            raise StationError('configuration_conflict', original.recorder)
        return original
