#!/usr/bin/env python3
"""Utility provider quarter-hourly CSV -> Home Assistant external statistics (Energy dashboard).

Usage:
  # one-off historical import from all emails
  python3 ha_import.py --daemon   # checks for unread "Napi riport" emails every 10 minutes
  python3 ha_import.py --mail
  # daily run: only emails from the last 7 days
  python3 ha_import.py --mail --days 7
  # manually downloaded CSVs (e.g. from the provider's portal)
  python3 ha_import.py --csv a.csv b.csv
  # check only, sends nothing
  python3 ha_import.py --csv a.csv --dry-run

Environment variables:
  HA_URL        e.g. ws://homeassistant.local:8123/api/websocket
  HA_TOKEN      long-lived access token
  IMAP_HOST, IMAP_USER, IMAP_PASSWORD, IMAP_FOLDER (default: INBOX)
  STORE         local storage for the quarter-hourly data (default: hourly_store.json)

Dependency: pip install websocket-client
"""
import argparse
import csv
import datetime as dt
import email
import imaplib
import io
import json
import os
import sys
import time
from email.header import decode_header
from zoneinfo import ZoneInfo

TZ = ZoneInfo("Europe/Budapest")
UTC = dt.timezone.utc

# (statistic_id, display name, column index in the CSV)
SERIES = [
    ("energia:halozati_vetel", "Hálózatból vételezett", 4),
    ("energia:halozatba_betaplalt", "Hálózatba betáplált", 8),
]
MONTHS = ["Jan", "Feb", "Mar", "Apr", "May", "Jun",
          "Jul", "Aug", "Sep", "Oct", "Nov", "Dec"]


def decode_bytes(b: bytes) -> str:
    for enc in ("utf-8-sig", "cp1250"):
        try:
            return b.decode(enc)
        except UnicodeDecodeError:
            pass
    return b.decode("latin-1")


def num(s: str) -> float:
    s = s.strip().replace(",", ".")
    return float(s) if s else 0.0


def parse_csv(text: str) -> dict:
    """Returns: {UTC start of quarter hour (ISO): [consumption, feed-in]}.

    The CSV timestamp is local time (Europe/Budapest) and marks the START of the quarter hour.
    At the clock change (last Sunday of October) 02:xx occurs twice: the fold handling
    resolves this based on row order.
    """
    out = {}
    rows = csv.reader(io.StringIO(text), delimiter=";")
    next(rows, None)  # header
    prev = None
    fold = 0
    for r in rows:
        if len(r) < 13 or not r[2].strip():
            continue
        try:
            naive = dt.datetime.strptime(
                r[2].strip() + " " + r[3].strip(), "%Y.%m.%d %H:%M:%S")
            vals = [num(r[i]) for _, _, i in SERIES]
        except ValueError:
            continue
        if prev is not None:
            if naive.date() != prev.date():
                fold = 0
            elif naive <= prev:
                fold = 1
        prev = naive
        key = naive.replace(tzinfo=TZ, fold=fold).astimezone(UTC).isoformat()
        out[key] = vals
    return out


def _store_path() -> str:
    return os.environ.get("STORE", "hourly_store.json")


def load_store() -> dict:
    STORE = _store_path()
    if os.path.exists(STORE):
        with open(STORE, encoding="utf-8") as f:
            return json.load(f)
    return {}


def save_store(store: dict) -> None:
    STORE = _store_path()
    with open(STORE, "w", encoding="utf-8") as f:
        json.dump(dict(sorted(store.items())), f)


def hourly(store: dict) -> dict:
    hours = {}
    for k, vals in store.items():
        t = dt.datetime.fromisoformat(k).replace(minute=0, second=0, microsecond=0)
        a = hours.setdefault(t, [0.0] * len(SERIES) + [0])
        for i, v in enumerate(vals):
            a[i] += v
        a[-1] += 1
    return dict(sorted(hours.items()))


def build_stats(hours: dict) -> list:
    """Per series: (statistic_id, name, [ {start, state, sum} ])."""
    result = []
    for idx, (sid, name, _) in enumerate(SERIES):
        total = 0.0
        pts = []
        for t, a in hours.items():
            total += a[idx]
            pts.append({"start": t.isoformat(),
                        "state": round(total, 6), "sum": round(total, 6)})
        result.append((sid, name, pts))
    return result


def upload(url: str, token: str, series: list) -> None:
    import websocket  # pip install websocket-client
    ws = websocket.create_connection(url)
    json.loads(ws.recv())  # auth_required
    ws.send(json.dumps({"type": "auth", "access_token": token}))
    if json.loads(ws.recv()).get("type") != "auth_ok":
        sys.exit("HA authentikacio sikertelen (token?)")
    msg_id = 0
    for sid, name, pts in series:
        meta = {"has_mean": False, "has_sum": True, "name": name,
                "source": sid.split(":")[0], "statistic_id": sid,
                "unit_of_measurement": "kWh"}
        for i in range(0, len(pts), 2000):
            msg_id += 1
            ws.send(json.dumps({"id": msg_id, "type": "recorder/import_statistics",
                                "metadata": meta, "stats": pts[i:i + 2000]}))
            res = json.loads(ws.recv())
            if not res.get("success"):
                sys.exit(f"Import hiba ({sid}): {res}")
        print(f"{sid}: {len(pts)} ora feltoltve")
    ws.close()


def _fname(part) -> str:
    fn = part.get_filename() or ""
    out = ""
    for b, enc in decode_header(fn):
        out += b.decode(enc or "utf-8", "replace") if isinstance(b, bytes) else b
    return out


def mail_csvs(days):
    m = imaplib.IMAP4_SSL(os.environ["IMAP_HOST"])
    m.login(os.environ["IMAP_USER"], os.environ["IMAP_PASSWORD"])
    m.select(os.environ.get("IMAP_FOLDER", "INBOX"), readonly=True)
    if days:
        d = dt.date.today() - dt.timedelta(days=days)
        crit = ["SINCE", f"{d.day:02d}-{MONTHS[d.month - 1]}-{d.year}"]
    else:
        crit = ["ALL"]
    _, data = m.search(None, *crit)
    ids = data[0].split()
    print(f"{len(ids)} level feldolgozasa")
    for n in ids:
        _, md = m.fetch(n, "(RFC822)")
        msg = email.message_from_bytes(md[0][1])
        for part in msg.walk():
            if _fname(part).lower().endswith(".csv"):
                yield decode_bytes(part.get_payload(decode=True))
    m.logout()


SUBJECT = "Napi riport"


def check_mail_once() -> None:
    """Loads the CSVs of unread 'Napi riport' emails into HA, then marks them as read.

    Returns True if at least one email was found and processed.
    """
    m = imaplib.IMAP4_SSL(os.environ["IMAP_HOST"])
    try:
        m.login(os.environ["IMAP_USER"], os.environ["IMAP_PASSWORD"])
        m.select(os.environ.get("IMAP_FOLDER", "INBOX"))
        _, data = m.search(None, "UNSEEN", "SUBJECT", f'"{SUBJECT}"')
        ids = data[0].split()
        if not ids:
            print("nincs uj level", flush=True)
            return False
        print(f"{len(ids)} uj level", flush=True)
        store = load_store()
        done = []
        for n in ids:
            _, md = m.fetch(n, "(BODY.PEEK[])")
            msg = email.message_from_bytes(md[0][1])
            csvs = [decode_bytes(p.get_payload(decode=True))
                    for p in msg.walk() if _fname(p).lower().endswith(".csv")]
            if not csvs:
                print(f"level {n.decode()}: nincs CSV melleklet, kihagyva", flush=True)
                continue
            for t in csvs:
                store.update(parse_csv(t))
            done.append(n)
        if not done:
            return False
        save_store(store)
        upload(os.environ["HA_URL"], os.environ["HA_TOKEN"], build_stats(hourly(store)))
        for n in done:  # only after a successful upload
            m.store(n, "+FLAGS", "\\Seen")
        print(f"{len(done)} level feldolgozva", flush=True)
        return True
    finally:
        try:
            m.logout()
        except Exception:
            pass


def daemon() -> None:
    interval = int(os.environ.get("CHECK_INTERVAL", "600"))
    found_sleep = 23 * 3600  # after an email was processed, sleep 23 hours
    while True:
        delay = interval
        try:
            if check_mail_once():
                delay = found_sleep
        except (Exception, SystemExit) as e:  # an error must not stop the scheduler
            print(f"HIBA: {e}", flush=True)
        time.sleep(delay)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--daemon", action="store_true",
                    help="10 percenkent uj 'Napi riport' level keresese")
    ap.add_argument("--mail", action="store_true")
    ap.add_argument("--days", type=int, default=None)
    ap.add_argument("--csv", nargs="*", default=[])
    ap.add_argument("--dry-run", action="store_true")
    a = ap.parse_args()
    if a.daemon:
        daemon()
        return

    store = load_store()
    new = 0
    texts = []
    for p in a.csv:
        with open(p, "rb") as f:
            texts.append(decode_bytes(f.read()))
    if a.mail:
        texts.extend(mail_csvs(a.days))
    for t in texts:
        parsed = parse_csv(t)
        new += len(parsed)
        store.update(parsed)  # overwrites values for the same quarter hour
    print(f"{new} negyedoras sor beolvasva, a tarban osszesen {len(store)}")

    hours = hourly(store)
    incomplete = [t for t, v in hours.items() if v[-1] != 4]
    if incomplete:
        print(f"FIGYELEM: {len(incomplete)} oraban nem 4 negyedora van "
              f"(pl. {incomplete[0].isoformat()})")

    series = build_stats(hours)
    if a.dry_run:
        for sid, _, pts in series[:1]:
            print(sid)
            for p in pts[:30]:
                print(" ", p)
        return
    save_store(store)
    upload(os.environ["HA_URL"], os.environ["HA_TOKEN"], series)

def read_dotenv(path=".env"):
    if not os.path.exists(path):
        return
    with open(path) as f:
        for line in f:
            line = line.strip()
            if not line or line.startswith("#"):
                continue
            key, value = line.split("=", 1)
            os.environ.setdefault(key, value)

if __name__ == "__main__":
    read_dotenv()
    main()