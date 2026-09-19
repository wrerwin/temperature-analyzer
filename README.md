# Temperature Volatility Analysis

How unusual, and how volatile, is the weather where you live? Enter a US zip code and compare
any day, year or decade against a century of daily records.

Live: https://wrerwin.github.io/temperature-analyzer/

**Year** (landing) — one year's hot and cold spells against the baseline normal, with ±1σ / ±2σ
bands; step through years, smooth 1–30 days, pin years to compare.

**Day** — where the selected day sits in the baseline distribution for that calendar day
(histogram with σ bands, z-score, percentile), plus that day in every year on record.

**Decades** — for every year, the number of days beyond +1/+2/+3σ (hot) and −1/−2/−3σ (cold),
counted separately, with decade averages and trends.

**Volatility** — a volatility index per year: the spread of daily anomalies around the year's own
mean (or the day-to-day swing), divided by the baseline average, so 1.0 = as volatile as the
baseline. Decade averages and trend.

**Map** — the Decades and Volatility numbers for ~300 stations across the contiguous US (1 in 100
zip codes), precomputed. Pick a threshold and a year, or press play to animate through time; drag
the strip under the map to scrub. Click a dot to open that zip code in the other tabs.

Options: baseline period (default earliest → 2000), history source (nearest long-record NOAA
station with ERA5 filling gaps, or ERA5 only), ±day window for the Day tab. Records are cached in
the browser so revisits only fetch the last two weeks.

## Running it

The site is a single static `index.html` plus two data files in `data/`; no build step, no keys.

```bash
python3 -m http.server 8765
```

Then open http://localhost:8765. GitHub Pages serves the `main` branch as is, so merging to `main`
deploys.

## Regenerating the map data

`data/geo-decades.json` is produced offline by the scripts in `analysis/` (Python 3, `numpy`,
`requests`). The cache they write (`analysis/cache/`, ~1 GB) is git-ignored.

```bash
python3 analysis/fetch_ghcn.py --thin 100   # 1 in 100 CONUS zips -> nearest long-record GHCN station, bulk NCEI files, ~10 min
python3 analysis/compute_decades.py         # per station-year sigma counts + volatility -> data/geo-decades.json
python3 analysis/make_outline.py            # state outlines -> data/conus-states.json (only if the map outline changes)
```

`--thin 10` samples ten times as many zips. `compute_decades.py` mirrors the page's own
climatology code exactly (verified against it), with `--b0/--b1` for the baseline and `--smooth`
for k-day smoothing. `fetch_era5.py` is an alternative fetcher using the Open-Meteo ERA5 archive,
but the free tier only allows ~20 full-history locations per day.

## Data sources

- **Zip → coordinates:** [zippopotam.us](https://www.zippopotam.us/) (site); [GeoNames postal codes](https://download.geonames.org/export/zip/) (map sampling, CC BY 4.0)
- **Station history:** NOAA [GHCN-Daily](https://www.ncei.noaa.gov/products/land-based-station/global-historical-climatology-network-daily)
  via the NCEI Access Data Service (site) and NCEI bulk `.dly` files (map). The nearest station
  within a ~0.5° box with the longest TMAX record (≥ 75% coverage, ≥ 30 years), with a mild
  distance penalty. Daily mean is (high + low) / 2.
- **Reanalysis (1940–present):** [Open-Meteo Historical Weather API](https://open-meteo.com/en/docs/historical-weather-api) (ERA5, ~5 day lag)
- **Recent days and today:** [Open-Meteo Forecast API](https://open-meteo.com/en/docs)
- **State outlines:** [us-atlas](https://github.com/topojson/us-atlas) (US Census, public domain), simplified

Caveats: station records can have gaps, instrument changes and relocations. ERA5 is a gridded
reanalysis (~9 km cells), not a station reading, and typically runs a degree or two cooler on daily
highs than a nearby station. Today's value always comes from the forecast model, so in "longest"
mode it is compared against a station-based baseline — expect a small cool bias in today's z-score.
