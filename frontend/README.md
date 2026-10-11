# SafeHaul frontend

React + TypeScript + Vite single-page app for the weather-aware truck routing planner.

## Run it

```bash
cp .env.example .env        # then edit .env
npm install
npm run dev                 # http://localhost:5173
```

`.env`:

| Variable | Value |
|---|---|
| `VITE_API_URL` | Django API, e.g. `http://localhost:8000` or your Render URL (no trailing slash) |
| `VITE_MAPBOX_TOKEN` | Mapbox **public** token (`pk...`) for drawing the map |

The Django backend must allow this origin: add it to `CORS_ALLOWED_ORIGINS` (`http://localhost:5173` for local dev).

## Scripts

| Command | What it does |
|---|---|
| `npm run dev` | dev server (listens on all interfaces) |
| `npm run build` | type-check, then production build to `dist/` |
| `npm test` | unit and render tests (Vitest) |
| `npm run typecheck` | TypeScript only |

## Data flow

```
type a place ──► GET /api/geocode/?q=…        debounced 300 ms, stale searches cancelled
Analyze      ──► POST /api/analyze/           3 routes, ranked, checkpoints, corridor
   then auto ──► POST /api/heatmap/           49 hourly frames for the corridor
slider       ──► reads frame N from memory    no network, map source updated with setData
```

* `src/api/`: typed client; backend errors become `ApiError` (code, message, retryable).
* `src/hooks/useTrip.ts`: analyze, then heatmap; responses from superseded requests are ignored.
* `src/lib/`: pure, unit-tested helpers (time zones, validation, formatting, GeoJSON building).
* `src/components/MapView.tsx` + `mapLayers.ts`: Mapbox sources/layers are created once; routes,
  checkpoints and heatmap frames are swapped with `setData`.

## Decisions

* Departure is entered in local time and sent as UTC with an explicit offset, so ETAs are never shifted.
* The map library is lazy-loaded so the form is interactive before it arrives.
* On phones the app has Plan and Map tabs, and jumps to the map when results arrive.
* Weather attribution (Open-Meteo, CC BY 4.0) is shown in the panel footer.

## Deploy (Vercel or Netlify)

Root directory `frontend`, build command `npm run build`, output directory `dist`, and set
`VITE_API_URL` and `VITE_MAPBOX_TOKEN` in the host's environment settings. Then add the deployed
URL to the backend's `CORS_ALLOWED_ORIGINS`.
