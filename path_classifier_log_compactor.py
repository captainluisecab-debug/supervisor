"""Weekly log compactor for path_classifier_log.jsonl.

Runs Sunday 23:59 ET (or any time the active log has data older than 6 days).
Rotates the log to a dated .gz archive and starts a fresh active file.
"""
import os, gzip, shutil, json
from datetime import datetime, timezone

LOG_PATH = r'C:\Projects\enzobot\logs\path_classifier_log.jsonl'
LOG_DIR = r'C:\Projects\enzobot\logs'


def main():
    if not os.path.exists(LOG_PATH):
        print('No active log to compact.')
        return 0

    oldest_ts = None
    with open(LOG_PATH, encoding='utf-8') as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            try:
                d = json.loads(line)
                oldest_ts = d.get('ts')
                break
            except Exception:
                continue

    if oldest_ts is None:
        print('Empty log, nothing to compact.')
        return 0

    now_ts = datetime.now(timezone.utc).timestamp()
    age_days = (now_ts - oldest_ts) / 86400.0
    print('Oldest record age: %.1f days' % age_days)

    if age_days < 6:
        print('Log too fresh to rotate (< 6 days). Skipping.')
        return 0

    oldest_dt = datetime.fromtimestamp(oldest_ts, tz=timezone.utc)
    year, week, _ = oldest_dt.isocalendar()
    archive_name = 'path_classifier_log_' + str(year) + '-W' + ('%02d' % week) + '.jsonl.gz'
    archive_path = os.path.join(LOG_DIR, archive_name)

    if os.path.exists(archive_path):
        print('Archive already exists:', archive_path)
        i = 1
        while os.path.exists(archive_path + '.' + str(i)):
            i += 1
        archive_path = archive_path + '.' + str(i)

    with open(LOG_PATH, 'rb') as f_in:
        with gzip.open(archive_path, 'wb') as f_out:
            shutil.copyfileobj(f_in, f_out)

    src_size = os.path.getsize(archive_path)

    with open(LOG_PATH, 'w', encoding='utf-8') as f:
        pass

    print('Rotated to:', archive_path)
    print('Archive size:', src_size, 'bytes')
    print('Active log truncated.')
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
