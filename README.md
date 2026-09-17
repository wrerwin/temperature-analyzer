# Temperature Analyzer

How unusual is today's temperature? Enter a US zip code and see where today falls
against every year back to 1940 for the same calendar day.

- Histogram of the daily high / low / mean for that date over a **baseline period** you choose
  (default: earliest record → 2000), with ±1σ, ±2σ, ±3σ bands shaded and today's value marked
- z-score, percentile, and a plain-English verdict ("within 1σ of normal — typical")
- Year-by-year series over the full record with a temperature / z-score toggle and a linear
  trend line; years outside the baseline are drawn hollow
- History source toggle: longest available (NOAA station record back to the 1800s where one
  exists, ERA5 filling gaps) or ERA5 reanalysis only (1940+)
- Optional ±3 / ±7 day window to widen the sample
- Full per-year table with data source per row

## Running it

It's a single static HTML file with no build step or API keys.

```bash
python -m http.server 8765
```

Then open http://localhost:8765. Opening `index.html` directly as a file also works.

## Data sources

- **Zip → coordinates:** [zippopotam.us](https://www.zippopotam.us/)
- **Station history:** NOAA [GHCN-Daily](https://www.ncei.noaa.gov/products/land-based-station/global-historical-climatology-network-daily)
  via the NCEI Access Data Service. The tool searches a ~0.5° box around the zip and picks the
  station with the longest TMAX record (≥ 75% coverage, ≥ 30 years), with a mild distance penalty.
  Daily mean is (high + low) / 2. Lags ~3 days.
- **Reanalysis (1940–present):** [Open-Meteo Historical Weather API](https://open-meteo.com/en/docs/historical-weather-api) (ERA5, ~5 day lag)
- **Recent days and today:** [Open-Meteo Forecast API](https://open-meteo.com/en/docs)

Caveats: station records can have gaps, instrument changes and relocations. ERA5 is a
gridded reanalysis (~9 km cells), not a station reading, and typically runs a degree or two
cooler on daily highs than a nearby station. Today's value always comes from the forecast
model, so in "longest" mode it is being compared against a station-based baseline — expect a
small cool bias in today's z-score. Today's high may still rise until evening.
