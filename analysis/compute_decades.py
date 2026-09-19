#!/usr/bin/env python3
"""Turn the cached daily records (fetch_ghcn.py, or fetch_era5.py) into the per-year "days beyond ±1/2/3σ"
counts the Decades tab shows, for every sampled location, and write data/geo-decades.json for the Map tab.

This mirrors index.html exactly (dailyIndex / climatology / computeAnomaly / drawDecades):
  * k-day centered mean of the daily value, null if < 60% of the k days are present
  * climatology for a calendar day = every baseline year's k-day mean pooled over ±7 calendar days
    (±3 when k > 1); the target year is left out (leave-one-out) before mean/sd are taken
  * z = (actual - mean) / sd; a year needs ≥ 30 valid days to count and ≥ 300 to be "complete"
  * hot bands: z > 1, > 2, > 3; cold bands: z < -1, < -2, < -3; counted separately
  * volatility: sd of the year's daily z around the year's own mean (spread) and the RMS day-to-day change in z
    (swing); the page normalises both by the baseline-period average so 1.0 = baseline-typical

    python3 analysis/compute_decades.py                      # GHCN cache, baseline 1940–2000, no smoothing
    python3 analysis/compute_decades.py --source era5 --smooth 1,7
"""
import argparse, glob, gzip, json, os, sys
from datetime import date, datetime, timedelta
import numpy as np

HERE = os.path.dirname(os.path.abspath(__file__))
CACHE = os.path.join(HERE, 'cache')
SOURCES = {'ghcn': 'NOAA GHCN-Daily (NCEI bulk files)', 'era5': 'ERA5 via Open-Meteo archive'}
OUT = os.path.join(os.path.dirname(HERE), 'data', 'geo-decades.json')
EPOCH = date(1970, 1, 1)


def epoch_day(y, m, d):
    """Days since 1970-01-01 for (year, 0-based month, day); day overflow rolls forward like JS Date.UTC."""
    return (date(y, m + 1, 1) - EPOCH).days + d - 1


def smoother(raw, lo, k):
    """Vectorised k-day centered mean at epoch days n (numpy array); NaN where < 60% of days present."""
    N = len(raw)
    present = ~np.isnan(raw)
    csum = np.concatenate([[0.0], np.cumsum(np.where(present, raw, 0.0))])
    ccnt = np.concatenate([[0], np.cumsum(present)])
    need = int(np.ceil(k * 0.6))
    h = k // 2

    def smooth(n):
        n = np.asarray(n)
        a = np.clip(n - h - lo, 0, N)
        b = np.clip(n - h - lo + k, 0, N)
        c = ccnt[b] - ccnt[a]
        s = csum[b] - csum[a]
        with np.errstate(invalid='ignore', divide='ignore'):
            out = np.where((a < b) & (c >= need), s / np.maximum(c, 1), np.nan)
        return out
    return smooth


def year_counts(raw, lo, k, base_years, first_year, last_year, today_n):
    """Per year: [hot1, hot2, hot3, cold1, cold2, cold3, n_valid, mean_anomaly, spread, swing] (None if < 30 valid days)."""
    smooth = smoother(raw, lo, k)
    pool = 7 if k == 1 else 3
    js = np.arange(-pool, pool + 1)

    # Climatology per calendar day (month, day) keyed like the JS: 366 keys incl. Feb 29.
    cal = [(m, d) for m in range(12) for d in range(1, [31, 29, 31, 30, 31, 30, 31, 31, 30, 31, 30, 31][m] + 1)]
    cal_idx = {md: i for i, md in enumerate(cal)}
    by = np.array(base_years)
    # centers[year_i, cal_i]
    centers = np.array([[epoch_day(y, m, d) for (m, d) in cal] for y in by])
    v = smooth(centers[:, :, None] + js[None, None, :])           # [year, cal, pool]
    ok = ~np.isnan(v)
    v0 = np.where(ok, v, 0.0)
    s1 = v0.sum(2); s2 = (v0 * v0).sum(2); c = ok.sum(2)           # per (base year, cal day)
    tot1, tot2, totc = s1.sum(0), s2.sum(0), c.sum(0)              # per cal day
    year_row = {y: i for i, y in enumerate(by)}

    out = []
    for y in range(first_year, last_year + 1):
        start, end = epoch_day(y, 0, 1), min(epoch_day(y, 11, 31), today_n)
        ns = np.arange(start, end + 1)
        actual = smooth(ns)
        days = [EPOCH + timedelta(days=int(n)) for n in ns]
        ci = np.array([cal_idx[(d.month - 1, d.day)] for d in days])
        # leave this year out of its own climatology
        if y in year_row:
            r = year_row[y]
            o1, o2, oc = s1[r, ci], s2[r, ci], c[r, ci]
        else:
            o1 = o2 = oc = 0
        cc = totc[ci] - oc
        m1 = tot1[ci] - o1; m2 = tot2[ci] - o2
        with np.errstate(invalid='ignore', divide='ignore'):
            mean = m1 / cc
            sd = np.sqrt(np.maximum(0.0, (m2 - cc * mean * mean) / (cc - 1)))
        valid = ~np.isnan(actual) & (cc >= 20) & (sd > 0)
        n = int(valid.sum())
        if n < 30:
            out.append(None); continue
        anom = actual[valid] - mean[valid]
        z = anom / sd[valid]
        spread = float(np.sqrt(((z - z.mean()) ** 2).mean()))
        vn = ns[valid]
        consecutive = np.diff(vn) == 1
        swing = float(np.sqrt((np.diff(z)[consecutive] ** 2).mean())) if consecutive.sum() >= 20 else None
        out.append([int((z > 1).sum() - (z > 2).sum()), int((z > 2).sum() - (z > 3).sum()), int((z > 3).sum()),
                    int((z < -1).sum() - (z < -2).sum()), int((z < -2).sum() - (z < -3).sum()), int((z < -3).sum()),
                    n, round(float(anom.mean()), 1) + 0.0, round(spread, 3), None if swing is None else round(swing, 3)])
    return out


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument('--b0', type=int, default=1940); ap.add_argument('--b1', type=int, default=2000)
    ap.add_argument('--smooth', default='1', help='comma-separated k values (default "1")')
    ap.add_argument('--source', choices=SOURCES, default='ghcn')
    ap.add_argument('--from-year', type=int, default=1900, help='drop years before this from the output (default 1900)')
    ap.add_argument('--out', default=OUT)
    a = ap.parse_args()
    ks = [int(x) for x in a.smooth.split(',')]

    files = sorted(glob.glob(os.path.join(CACHE, a.source, '[0-9]*.json.gz')))
    if not files:
        sys.exit(f'no cached records in cache/{a.source}; run fetch_{a.source}.py first')
    today_n = (date.today() - EPOCH).days
    locs, spans, data = [], [], {m: {str(k): [] for k in ks} for m in ('max', 'min', 'mean')}
    first_year = last_year = None
    for i, f in enumerate(files, 1):
        rec = json.load(gzip.open(f, 'rt', encoding='utf-8'))
        y0, m0, d0 = map(int, rec['start'].split('-'))
        lo = epoch_day(y0, m0 - 1, d0)
        mx = np.array([np.nan if v is None else v for v in rec['max']], dtype=float)
        mn = np.array([np.nan if v is None else v for v in rec['min']], dtype=float)
        series = {'max': mx, 'min': mn, 'mean': (mx + mn) / 2}
        fy, ly = max(y0, a.from_year), int(rec['end'][:4])
        first_year, last_year = fy if first_year is None else min(first_year, fy), ly if last_year is None else max(last_year, ly)
        base_years = list(range(max(fy, a.b0), min(ly + 1, a.b1) + 1))
        locs.append({k: rec[k] for k in ('zip', 'place', 'state', 'lat', 'lon', 'station') if k in rec})
        spans.append((fy, ly))
        for m, raw in series.items():
            for k in ks:
                data[m][str(k)].append(year_counts(raw, lo, k, base_years, fy, ly, today_n))
        print(f'[{i}/{len(files)}] {rec["zip"]} {rec["place"]}, {rec["state"]}', file=sys.stderr)

    years = list(range(first_year, last_year + 1))
    for m in data:
        for k in data[m]:
            for row, (fy, ly) in zip(data[m][k], spans):      # pad to the common year axis
                row[:0] = [None] * (fy - first_year)
                row += [None] * (last_year - ly)
    out = {
        'meta': {'generated': datetime.now().isoformat(timespec='seconds'), 'source': SOURCES[a.source],
                 'baseline': [a.b0, a.b1], 'smooth': ks, 'locations': len(locs),
                 'fields': ['hot1', 'hot2', 'hot3', 'cold1', 'cold2', 'cold3', 'n', 'anom', 'spread', 'swing'],
                 'note': 'per location, per year: days with z in (1,2], (2,3], >3 (hot) and [-2,-1), [-3,-2), <-3 (cold); n valid days; mean anomaly °F; sd of daily z about the year mean; RMS day-to-day change in z'},
        'years': years, 'locations': locs, 'data': data,
    }
    os.makedirs(os.path.dirname(a.out), exist_ok=True)
    with open(a.out, 'w') as f:
        json.dump(out, f, separators=(',', ':'))
    print(f'wrote {a.out}: {len(locs)} locations × {len(years)} years, {os.path.getsize(a.out)/1e6:.1f} MB', file=sys.stderr)


if __name__ == '__main__':
    main()
