#!/usr/bin/env python3
"""Fetch full NOAA GHCN-Daily station records for a thinned sample of contiguous-US zip codes.

Uses NCEI's bulk files (no API quota, no key): the one-file station inventory picks, for each sampled
zip, the station the site's "Longest" mode would pick — within a ~0.5° box, the longest TMAX record
(≥ 30 years, ≥ 75% daily coverage) with a mild distance penalty — then downloads that station's .dly file.
Zip list: GeoNames US postal codes (CC BY 4.0). Cached per station in analysis/cache/ghcn/ so re-runs are free.

    python3 analysis/fetch_ghcn.py --thin 100          # ~365 zips, a few minutes
    python3 analysis/fetch_ghcn.py --thin 10
"""
import argparse, gzip, json, math, os, sys, time
from datetime import date, timedelta
import requests
from fetch_era5 import load_zips, sample, CACHE

GHCN_DIR = os.path.join(CACHE, 'ghcn')
DLY_DIR = os.path.join(GHCN_DIR, 'dly')
PUB = 'https://www.ncei.noaa.gov/pub/data/ghcn/daily/'
BOX = 0.5
EPOCH = date(1970, 1, 1)


def download(url, session):
    """GET with retries; NCEI occasionally drops connections mid-run."""
    for attempt in range(6):
        try:
            r = session.get(url, timeout=300)
            if r.status_code < 500:
                r.raise_for_status()
                return r.content
            msg = f'HTTP {r.status_code}'
        except requests.RequestException as e:
            msg = str(e)
        wait = 10 * 2 ** attempt
        print(f'  {url.rsplit("/", 1)[-1]}: {msg}; retry in {wait}s', file=sys.stderr)
        time.sleep(wait)
    raise RuntimeError(f'gave up downloading {url}')


def get_file(name, session):
    path = os.path.join(GHCN_DIR, name)
    if not os.path.exists(path):
        print(f'downloading {name}…', file=sys.stderr)
        open(path, 'wb').write(download(PUB + name, session))
    return path


def load_inventory(session):
    """US stations with a TMAX record: id -> {lat, lon, name, first, last}."""
    names = {}
    for line in open(get_file('ghcnd-stations.txt', session), encoding='utf-8'):
        if line.startswith('US'):
            names[line[:11]] = line[41:71].strip()
    inv = {}
    for line in open(get_file('ghcnd-inventory.txt', session), encoding='utf-8'):
        if line.startswith('US') and line[31:35] == 'TMAX':
            sid = line[:11]
            inv[sid] = {'id': sid, 'lat': float(line[12:20]), 'lon': float(line[21:30]), 'name': names.get(sid, sid),
                        'first': int(line[36:40]), 'last': int(line[41:45])}
    return inv


def haversine_mi(lat1, lon1, lat2, lon2):
    R, to_r = 3958.8, math.pi / 180
    dlat, dlon = (lat2 - lat1) * to_r, (lon2 - lon1) * to_r
    a = math.sin(dlat / 2) ** 2 + math.cos(lat1 * to_r) * math.cos(lat2 * to_r) * math.sin(dlon / 2) ** 2
    return 2 * R * math.asin(math.sqrt(a))


def candidates(z, inv, min_last):
    out = []
    for st in inv.values():
        if abs(st['lat'] - z['lat']) > BOX or abs(st['lon'] - z['lon']) > BOX:
            continue
        years = st['last'] - st['first'] + 1
        if years < 30 or st['last'] < min_last:
            continue
        dist = haversine_mi(z['lat'], z['lon'], st['lat'], st['lon'])
        # Same shape as the site's score (coverage is unknown until the file is read; checked after download).
        out.append((years - dist * 0.4, dist, st))
    out.sort(key=lambda t: -t[0])
    return out


def parse_dly(text):
    """.dly fixed-width -> {(y, m, d): [tmax_F, tmin_F]}; quality-flagged values dropped; tenths of °C -> °F."""
    days = {}
    for line in text.splitlines():
        el = line[17:21]
        if el not in ('TMAX', 'TMIN'):
            continue
        y, m = int(line[11:15]), int(line[15:17])
        for d in range(31):
            o = 21 + d * 8
            v, q = line[o:o + 5], line[o + 6]
            if v == '-9999' or q.strip():
                continue
            f = round(int(v) / 10 * 9 / 5 + 32, 1)
            rec = days.setdefault((y, m, d + 1), [None, None])
            rec[0 if el == 'TMAX' else 1] = f
    return days


def station_record(st, session):
    """Dense daily arrays for one station (cached parse), plus coverage of TMAX over its span."""
    cache = os.path.join(GHCN_DIR, f'{st["id"]}.json.gz')
    if os.path.exists(cache):
        return json.load(gzip.open(cache, 'rt', encoding='utf-8'))
    os.makedirs(DLY_DIR, exist_ok=True)
    dly = os.path.join(DLY_DIR, st['id'] + '.dly')
    if not os.path.exists(dly):
        open(dly, 'wb').write(download(f'{PUB}all/{st["id"]}.dly', session))
    days = parse_dly(open(dly, encoding='utf-8').read())
    keys = sorted(k for k, v in days.items() if v[0] is not None or v[1] is not None)
    if not keys:
        return None
    valid = []
    for k in keys:
        try: valid.append((date(*k), days[k]))
        except ValueError: pass    # bad calendar dates in the fixed-width block are impossible, but be safe
    d0, d1 = valid[0][0], valid[-1][0]
    n = (d1 - d0).days + 1
    mx, mn = [None] * n, [None] * n
    tmax_n = 0
    for d, (a, b) in valid:
        i = (d - d0).days
        mx[i], mn[i] = a, b
        tmax_n += a is not None
    rec = {'id': st['id'], 'name': st['name'], 'slat': st['lat'], 'slon': st['lon'], 'start': d0.isoformat(), 'end': d1.isoformat(),
           'coverage': round(100 * tmax_n / n, 1), 'max': mx, 'min': mn}
    with gzip.open(cache, 'wt', encoding='utf-8') as f:
        json.dump(rec, f, separators=(',', ':'))
    return rec


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument('--thin', type=int, default=100, help='keep 1 of every N CONUS zips (default 100)')
    ap.add_argument('--offset', type=int, default=0)
    ap.add_argument('--limit', type=int, default=0, help='stop after this many zips (0 = no limit)')
    ap.add_argument('--min-last', type=int, default=date.today().year - 1, help='station must report through this year')
    ap.add_argument('--min-coverage', type=float, default=75.0)
    ap.add_argument('--sleep', type=float, default=0.3)
    a = ap.parse_args()

    os.makedirs(GHCN_DIR, exist_ok=True)
    s = requests.Session()
    s.headers['User-Agent'] = 'temperature-analyzer geo fetch (github.com/wrerwin/temperature-analyzer)'
    inv = load_inventory(s)
    zips = sample(load_zips(), a.thin, a.offset)
    if a.limit:
        zips = zips[:a.limit]
    print(f'{len(inv)} US TMAX stations; {len(zips)} sampled zips (thin={a.thin}, offset={a.offset})', file=sys.stderr)

    # One output row per station: zips that resolve to an already-used station are skipped (they'd be identical points).
    used, out, t0 = {}, [], time.time()
    for i, z in enumerate(zips, 1):
        chosen = None
        for _, dist, st in candidates(z, inv, a.min_last):
            if st['id'] in used:
                chosen = ('dup', st, dist); break
            rec = station_record(st, s)
            time.sleep(a.sleep)
            if rec and rec['coverage'] >= a.min_coverage:
                chosen = ('new', st, dist, rec); break
        if not chosen:
            print(f'[{i}/{len(zips)}] {z["zip"]} {z["place"]}, {z["state"]}: no qualifying station', file=sys.stderr); continue
        if chosen[0] == 'dup':
            print(f'[{i}/{len(zips)}] {z["zip"]} {z["place"]}, {z["state"]}: shares {chosen[1]["id"]} with {used[chosen[1]["id"]]}, skipped', file=sys.stderr); continue
        _, st, dist, rec = chosen
        used[st['id']] = z['zip']
        loc = {'zip': z['zip'], 'place': z['place'], 'state': z['state'], 'lat': z['lat'], 'lon': z['lon'],
               'station': {'id': st['id'], 'name': st['name'], 'dist': round(dist, 1), 'coverage': rec['coverage'], 'start': rec['start'][:4], 'end': rec['end'][:4]},
               'start': rec['start'], 'end': rec['end'], 'max': rec['max'], 'min': rec['min']}
        with gzip.open(os.path.join(GHCN_DIR, f'{z["zip"]}.json.gz'), 'wt', encoding='utf-8') as f:
            json.dump(loc, f, separators=(',', ':'))
        out.append(z['zip'])
        print(f'[{i}/{len(zips)}] {z["zip"]} {z["place"]}, {z["state"]} -> {st["id"]} {st["name"]} ({dist:.0f} mi, {rec["start"][:4]}–{rec["end"][:4]}, {rec["coverage"]}%)  {time.time()-t0:.0f}s', file=sys.stderr)
    print(f'done: {len(out)} locations', file=sys.stderr)


if __name__ == '__main__':
    main()
