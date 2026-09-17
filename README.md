# Temperature Analyzer

How unusual is today's temperature? Enter a US zip code and see where today falls
against every year back to 1940 for the same calendar day.

- Histogram of the historical daily high / low / mean for that date, with ±1σ, ±2σ, ±3σ
  bands shaded and today's value marked
- z-score, percentile, and a plain-English verdict ("within 1σ of normal — typical")
- Year-by-year series with a temperature / z-score toggle and a linear trend line
- Optional ±3 / ±7 day window to widen the sample
- Full per-year table

## Running it

It's a single static HTML file with no build step or API keys.

```bash
python -m http.server 8765
```

Then open http://localhost:8765. Opening `index.html` directly as a file also works.

## Data sources

- **Zip → coordinates:** [zippopotam.us](https://www.zippopotam.us/)
- **History (1940–present):** [Open-Meteo Historical Weather API](https://open-meteo.com/en/docs/historical-weather-api) (ERA5 reanalysis, ~5 day lag)
- **Recent days and today:** [Open-Meteo Forecast API](https://open-meteo.com/en/docs)

ERA5 is a gridded reanalysis (~9 km cells), not a station reading, so values may differ
by a degree or two from a local thermometer — but it's consistent across all 86 years,
which is what matters for the distribution. Today's high may still rise until evening.
