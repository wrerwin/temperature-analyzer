#!/usr/bin/env python3
"""Fetch ERA5 daily high/low (1940 -> ~a week ago) for a thinned sample of contiguous-US zip codes.

Zip list: GeoNames US postal codes (CC BY 4.0), downloaded once into the cache dir.
Sampling: CONUS zips sorted by zip code, every Nth one (--thin), so density is a single knob;
zip prefixes are regional, so a stride still spreads the sample across the country.
Each location's raw record is cached gzipped in analysis/cache/era5/ so the run is resumable
and re-runs cost no API calls.

    python3 analysis/fetch_era5.py --thin 100          # ~405 zips, ~15 min
    python3 analysis/fetch_era5.py --thin 10           # ~4000 zips (expect Open-Meteo rate limits)
"""
import argparse, csv, gzip, io, json, os, sys, time, zipfile
from datetime import date, timedelta
import requests

HERE = os.path.dirname(os.path.abspath(__file__))
CACHE = os.path.join(HERE, 'cache')
ERA5_DIR = os.path.join(CACHE, 'era5')
GEONAMES_URL = 'https://download.geonames.org/export/zip/US.zip'
NON_CONUS = {'AK', 'HI', 'PR', 'GU', 'VI', 'AS', 'MP', 'FM', 'MH', 'PW', 'AA', 'AE', 'AP'}
OM_URL = ('https://archive-api.open-meteo.com/v1/archive?latitude={lat}&longitude={lon}'
          '&daily=temperature_2m_max,temperature_2m_min&temperature_unit=fahrenheit&timezone=auto'
          '&start_date=1940-01-01&end_date={end}')


def load_zips():
    """All CONUS zips as dicts, sorted by zip code; identical coordinates (PO-box zips) collapsed."""
    path = os.path.join(CACHE, 'US.txt')
    if not os.path.exists(path):
        os.makedirs(CACHE, exist_ok=True)
        print('downloading GeoNames US postal codes…', file=sys.stderr)
        z = zipfile.ZipFile(io.BytesIO(requests.get(GEONAMES_URL, timeout=120).content))
        open(path, 'wb').write(z.read('US.txt'))
    out, seen = [], set()
    with open(path, encoding='utf-8') as f:
        for r in csv.reader(f, delimiter='\t'):
            st, lat, lon = r[4], r[9], r[10]
            if not st or st in NON_CONUS or not lat or not lon:
                continue
            key = (round(float(lat), 2), round(float(lon), 2))
            if key in seen:
                continue
            seen.add(key)
            out.append({'zip': r[1], 'place': r[2], 'state': st, 'lat': float(lat), 'lon': float(lon)})
    out.sort(key=lambda z: z['zip'])
    return out


def sample(zips, thin, offset):
    return [z for i, z in enumerate(zips) if i % thin == offset]


def cache_path(zip_code):
    return os.path.join(ERA5_DIR, f'{zip_code}.json.gz')


def fetch_one(z, end, sleep, session):
    """One archive call with retry on 429/5xx; returns the parsed daily block."""
    url = OM_URL.format(lat=z['lat'], lon=z['lon'], end=end)
    wait = 60
    for attempt in range(8):
        try:
            r = session.get(url, timeout=90)
        except requests.RequestException as e:
            print(f'  {z["zip"]}: {e}; retry in {wait}s', file=sys.stderr); time.sleep(wait); wait *= 2; continue
        if r.status_code == 429 or r.status_code >= 500:
            print(f'  {z["zip"]}: HTTP {r.status_code}; sleeping {wait}s', file=sys.stderr)
            time.sleep(wait); wait = min(wait * 2, 900); continue
        r.raise_for_status()
        try:
            j = r.json()
        except ValueError:
            j = None
        if not j or 'daily' not in j:   # e.g. "Unexpected error while streaming data: timeoutReached", or {"error":true,...}
            msg = (j or {}).get('reason') if isinstance(j, dict) else r.text[:120]
            print(f'  {z["zip"]}: bad response ({msg}); retry in 5s', file=sys.stderr); time.sleep(5); continue
        d = j['daily']
        time.sleep(sleep)
        return {'zip': z['zip'], 'place': z['place'], 'state': z['state'], 'lat': z['lat'], 'lon': z['lon'],
                'start': d['time'][0], 'end': d['time'][-1], 'max': d['temperature_2m_max'], 'min': d['temperature_2m_min']}
    raise RuntimeError(f'{z["zip"]}: gave up after repeated failures')


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument('--thin', type=int, default=100, help='keep 1 of every N CONUS zips (default 100)')
    ap.add_argument('--offset', type=int, default=0, help='which residue class mod N to keep (default 0)')
    ap.add_argument('--limit', type=int, default=0, help='stop after this many fetches (0 = no limit)')
    ap.add_argument('--sleep', type=float, default=1.0, help='seconds between calls (default 1.0)')
    ap.add_argument('--end', default=(date.today() - timedelta(days=7)).isoformat(), help='last date to request')
    a = ap.parse_args()

    zips = sample(load_zips(), a.thin, a.offset)
    os.makedirs(ERA5_DIR, exist_ok=True)
    todo = [z for z in zips if not os.path.exists(cache_path(z['zip']))]
    print(f'{len(zips)} sampled zips (thin={a.thin}, offset={a.offset}); {len(zips) - len(todo)} cached, {len(todo)} to fetch', file=sys.stderr)
    if a.limit:
        todo = todo[:a.limit]

    s = requests.Session()
    s.headers['User-Agent'] = 'temperature-analyzer geo fetch (github.com/wrerwin/temperature-analyzer)'
    t0 = time.time()
    for i, z in enumerate(todo, 1):
        rec = fetch_one(z, a.end, a.sleep, s)
        with gzip.open(cache_path(z['zip']), 'wt', encoding='utf-8') as f:
            json.dump(rec, f, separators=(',', ':'))
        el = time.time() - t0
        print(f'[{i}/{len(todo)}] {z["zip"]} {z["place"]}, {z["state"]}  {el/i:.1f}s/loc, ~{(len(todo)-i)*el/i/60:.0f} min left', file=sys.stderr)
    print('done', file=sys.stderr)


if __name__ == '__main__':
    main()
