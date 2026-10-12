# SafeHaul: weather-aware truck routing

SafeHaul helps a truck driver choose the safest of three routes. It forecasts the weather at the time the truck will actually reach each point on each route, scores the risk using the load-weight rules, recommends a route, and shows a 0 to 48 hour weather heatmap along the corridor.

| | |
|---|---|
| Live app | https://safe-haul-eight.vercel.app/ |
| API | https://safehaul.onrender.com (health check: `/api/health/`) |
| Walkthrough | `TODO: Loom link` |

> The API runs on free hosting and sleeps when idle. The first request after a quiet period can take up to a minute; the app shows a note when this happens.

---

## What the driver does

1. Enters an **origin and destination** (autocomplete), a **departure date and time**, and a **load weight** in pounds.
2. Gets **three route options**, ranked, with drive time, distance, arrival time and a bar showing how many miles sit at each risk level.
3. Sees a **recommendation with the reason** ("fewest Severe miles: 0.0 mi vs 12.4 mi on the next best route").
4. Explores the **map**: routes, risk-coloured checkpoints (ETA, wind, rain, snow, reason), and a **weather heatmap with a 0 to 48 hour slider**.

---

## Run it locally

Requirements: Python 3.12+, Node 20.19+ (22.12+ recommended), a Mapbox account.

```bash
# Backend
cd backend
python -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt
cp .env.example .env            # set MAPBOX_TOKEN (see Configuration)
python manage.py runserver      # http://localhost:8000
python -m pytest -q             # backend tests

# Frontend (second terminal)
cd frontend
cp .env.example .env            # set VITE_API_URL and VITE_MAPBOX_TOKEN
npm install
npm run dev                     # http://localhost:5173
npm test                        # frontend tests
```

---

## Architecture

```
React + Vite (Vercel)                         Django REST (Render)                  External APIs
─────────────────────                         ────────────────────                  ─────────────
PlaceInput  ── GET  /api/geocode/ ─────────►  geocoding.py ──────────────────────►  Mapbox Geocoding v6
TripForm    ── POST /api/analyze/ ─────────►  analysis.py (orchestrator)
                                                ├ routing.py ────────────────────►  Mapbox Directions
                                                ├ sampling.py   (checkpoints + ETAs)
                                                ├ weather.py ────────────────────►  Open-Meteo (batched, cached)
                                                ├ risk.py       (thresholds + load rules)
                                                ├ recommend.py  (route stats + ranking)
                                                └ geometry.py   (simplify drawn line)
HeatmapControl ─ POST /api/heatmap/ ───────►  heatmap.py (reuses weather cache + risk.py)
MapView (Mapbox GL): routes, checkpoints, heatmap frames
```

### Backend (`backend/`)

The code is split into a **pure logic layer** with no network or Django imports, and thin **I/O wrappers**. The logic carries the correctness requirements, so it is the most heavily unit tested.

| Module | Role | I/O |
|---|---|---|
| `services/risk.py` | wind/rain/snow thresholds, load rules, human-readable reason | pure |
| `services/recommend.py` | miles per risk level, average risk, ranking, "why" text | pure |
| `services/sampling.py` | checkpoint spacing, polyline interpolation, ETAs | pure |
| `services/geometry.py` | Douglas-Peucker simplification of the drawn line | pure |
| `services/analysis.py` | wires everything together for one trip | pure (clients injected) |
| `services/heatmap.py` | risk per corridor point for hours 0..48 | uses weather client |
| `services/routing.py` | Mapbox Directions client and detour fallback | HTTP |
| `services/geocoding.py` | Mapbox Geocoding client | HTTP |
| `services/weather.py` | Open-Meteo client: batching, cache, stale fallback | HTTP |
| `api/` | request validation, error mapping, four endpoints | Django/DRF |

### Frontend (`frontend/src/`)

| Folder | Role |
|---|---|
| `api/` | typed client; backend errors become `ApiError` (code, message, retryable) |
| `hooks/` | `useTrip` (analyze, then heatmap, ignoring stale responses), `useDebounce`, `useMediaQuery` |
| `lib/` | pure, unit-tested helpers: time zones, validation, formatting, GeoJSON building, risk colours |
| `components/` | form, autocomplete, route cards, checkpoint list, map, heatmap control, status panels |

### API

| Endpoint | Purpose |
|---|---|
| `GET /api/health/` | liveness check |
| `GET /api/geocode/?q=…` | up to 5 place suggestions |
| `POST /api/analyze/` | 3 routes with checkpoints, weather, risk, ranking, and the heatmap `corridor` points |
| `POST /api/heatmap/` | risk level and conditions for each corridor point for each hour 0..48 |

`POST /api/analyze/` takes `origin` and `destination` (each `{lat, lon, label}` or `{query}`), `departure` (ISO 8601 **with a timezone offset**) and `load_lb`. Failures return `{"error": {"code", "message", "fields?"}}` with these codes: `invalid_request` (400), `invalid_trip` (400), `place_not_found` (404), `no_route` (404), `forecast_unavailable` (422), `upstream_unavailable` (502), `upstream_error` (502).

### Data flow

```
type a place ──► debounced 300 ms, in-flight search cancelled when a newer one starts
Analyze      ──► ONE request returns routes, checkpoints, weather, risk, ranking, corridor
   then auto ──► heatmap request: 49 hourly frames for the corridor
slider       ──► reads frame N from memory: no network call, map source updated with setData
```

---

## The risk model as implemented

**Per-condition level** (the brief's table overlaps at its edges, so the boundaries are explicit):

| | Low | Moderate | High | Severe | No Travel |
|---|---|---|---|---|---|
| Wind (mph), lower bound inclusive | < 25 | ≥ 25 | ≥ 35 | ≥ 45 | ≥ 55 |
| Rain (in/hr), upper bound inclusive | < 0.10 | 0.10 to 0.25 | > 0.25 to 0.50 | > 0.50 to 1.00 | > 1.00 |
| Snow (in/hr), upper bound inclusive | < 0.5 | 0.5 to 1.0 | > 1.0 to 2.0 | > 2.0 to 3.0 | > 3.0 |

Rain and snow use upper-inclusive bands because the brief says No Travel is strictly "> 1.00" and "> 3.0", which makes 1.00 and 3.0 Severe. Every boundary value is covered by a test.

**Checkpoint risk** = the worst of wind, rain and snow, then the **load rules escalate it, never lower it**:

| Wind | Load | Result |
|---|---|---|
| ≥ 55 mph | any | No Travel |
| 45 to 54 mph | > 30,000 lb | No Travel |
| 35 to 44 mph | > 40,000 lb | at least Severe |

The thresholds are strict: exactly 30,000 lb or 40,000 lb does not trigger the rule.

## Route recommendation

For each route, every checkpoint "owns" the road halfway to its neighbours on either side (the first owns from mile 0, the last to the destination). Summing that by risk level gives **Severe miles, High miles and No Travel miles**, plus a **mileage-weighted average risk** (Low = 1 … No Travel = 5).

Routes are ranked strictly in the order the brief gives, lower is better at each step:

1. Fewest **Severe** miles
2. Fewest **High** miles
3. Lowest **average risk**
4. Shortest **travel time**

**Addition beyond the brief:** a route with any **No Travel** miles ranks below every route without, and No Travel miles are compared first. If every route is blocked, the least blocked wins and the UI warns the driver. Miles are compared at 0.01 mi (and risk at 0.001, time in whole seconds) so floating-point noise never decides a ranking. Full ties keep the order the routing API returned.

---

## Assumptions and interpretations

The brief leaves several points open. These are the choices made, and where each lives in the code.

| # | Brief says | Interpreted as |
|---|---|---|
| 1 | "Sample weather every 10 / 25 / 50 miles" | **Adaptive spacing by trip length**: under 150 mi → every 10 mi; 150 to 500 mi → 25 mi; over 500 mi → 50 mi. Origin and destination are always included; a checkpoint within 25% of the spacing from the destination is dropped. (`sampling.py`) |
| 2 | Weather "using the truck's ETA at each checkpoint" | ETA = departure + cumulative drive time from the routing API's **per-segment durations**, scaled to the route total. Falls back to constant speed if unavailable. The forecast hour used is the nearest hour (half-hours round up). |
| 3 | "0 to 48 hour forecast slider" | **Hours after departure**, with hour 0 = departure time. Near the 16-day forecast limit the slider shortens instead of failing. |
| 4 | "Weather heatmap along the trip corridor" | Evenly spaced points along **all three routes** (about 40 per route, merged per weather cell), rendered as a heatmap. Low risk has zero weight so only Moderate and worse glows. |
| 5 | "Wind" | **Sustained 10 m wind speed**, not gusts. Switch with `WEATHER_WIND_METRIC=gust` (more conservative). |
| 6 | "Rain" and "Snow" rates | Rain = Open-Meteo `rain` + `showers` (inches per hour); snow = `snowfall` in inches per hour. Missing values count as 0. |
| 7 | "Load weight" | Pounds, 0 to 150,000. |
| 8 | "Generate 3 route options" | Mapbox alternatives first; if fewer than 3 come back, **detour routes** via a waypoint offset sideways from the midpoint are tried, and kept only if they are distinct (≥ 20% of the route far from existing ones) and not more than 1.75× the fastest duration. Fewer than 3 can still be returned. |
| 9 | "Departure date/time" | Must carry a timezone offset (naive times are rejected so ETAs can't silently shift). The UI converts local time to UTC. Must be no more than 1 hour in the past and within 16 days. |
| 10 | "Average risk" | Mileage-weighted mean of levels 1 to 5, not a simple mean of checkpoints. |
| 11 | "Recommend the best route, balancing weather risk and travel time" | Implemented as the strict priority order in the brief's own Route Recommendation list. |

---

## Key design decisions

| Decision | Why |
|---|---|
| **Monorepo** with `backend/` and `frontend/` | one clone, one README; Render and Vercel both deploy from a sub-folder |
| **Pure logic layer, injected clients** | the correctness-critical parts are unit tested with no network; every external service is replaceable with a fake |
| **One analysis request** that returns routes, checkpoints, weather, risk and ranking | one round trip instead of one per route or checkpoint |
| **Batched, deduplicated weather calls** (up to 50 points each, grid-snapped to 0.1° ≈ 7 mi) | overlapping routes and nearby checkpoints share one fetch; this is what keeps API usage low |
| **`/analyze` prefetches the heatmap's data** in the same weather fetch | the heatmap request then makes no provider calls |
| **Heatmap returns all 49 hours at once** | the slider is a client-side array lookup, so it is instant and works offline once loaded |
| **Map layers created once, data swapped with `setData`** | no layer rebuilds on slider moves, so it stays smooth |
| **Route geometry simplified for drawing only** (≈ 50 m tolerance, max 2,500 points) | far smaller responses; checkpoints and ETAs still use the full geometry |
| **Weather cache: 1 hour fresh + 6 hours stale-if-error** | if the provider rate-limits or fails, slightly older forecasts are served instead of an error |
| **Single gunicorn worker with 8 threads** | the weather cache is in-process, so one worker shares it across requests |
| **Lazy-loaded map**, plain CSS, no state library | the form is interactive before the 1.8 MB map library arrives; fewer dependencies |
| **Tapping a route has a wide invisible hit area** | easy to select on a phone |
| **Plan / Map tabs on phones**, jump to the map when results arrive | a usable full-screen map and heatmap on small screens |
| **No database** | nothing needs to persist; the app is stateless apart from the cache |

---

## Performance

- One weather fetch per analysis, batched and parallel (up to 4 requests at a time).
- Repeat or overlapping trips within an hour are served from cache.
- Autocomplete is debounced and cancels stale searches, so slow responses can't overwrite fresh ones.
- API responses are small: simplified geometry, rounded numbers.
- The heatmap makes one request per analysis; moving the slider makes none.

## Testing

- **Backend: 227 tests (pytest).** Boundary values for every threshold, each load rule, ranking priority and tie handling, ETA interpolation, weather batching, caching and stale fallback, routing and geocoding parsing and retries, API validation and error mapping, and an end-to-end check that the heatmap makes **zero** provider calls after an analysis.
- **Frontend: 70 tests (Vitest).** Time-zone conversion, form validation, formatting, GeoJSON building, API client error handling, and render tests for the main components.
- External APIs are faked in tests. The real services were checked by hand (smoke tests against Open-Meteo, Mapbox Directions and Mapbox Geocoding, and the full deployed flow).
- The map itself (WebGL) has no automated test; it was checked manually in the browser.

---

## Configuration

**Backend (Render environment variables)**

| Variable | Purpose |
|---|---|
| `MAPBOX_TOKEN` | routing and geocoding (required) |
| `DJANGO_SECRET_KEY` | required when `DJANGO_DEBUG=0` |
| `DJANGO_DEBUG` | `0` in production |
| `DJANGO_ALLOWED_HOSTS` | extra hosts (the Render hostname is added automatically) |
| `CORS_ALLOWED_ORIGINS` | comma-separated frontend origins, exact `https://…` with no trailing slash |
| `GEOCODE_COUNTRY` | optional, e.g. `us,ca` to limit suggestions |
| `WEATHER_WIND_METRIC` | optional, `sustained` (default) or `gust` |
| `PYTHON_VERSION` | e.g. `3.12.8` |

Render settings: root directory `backend`, build `pip install -r requirements.txt`, start `gunicorn config.wsgi:application --workers 1 --threads 8 --timeout 60`.

**Frontend (Vercel environment variables, baked in at build time)**

| Variable | Purpose |
|---|---|
| `VITE_API_URL` | the API address, no trailing slash |
| `VITE_MAPBOX_TOKEN` | Mapbox **public** token for drawing the map |

Vercel settings: root directory `frontend`, build `npm run build`, output `dist`. Redeploy after changing a variable.

---

## Known limitations

**Routing**
- Mapbox has **no truck profile**. Routes are standard driving routes: no height, weight or hazmat restrictions, and no truck-prohibited roads.
- Fewer than three routes can be returned when no sufficiently different alternative exists. The UI handles one or two.
- Detour routes are a heuristic (a sideways waypoint). They are filtered for similarity and detour length, but are not guaranteed to be sensible.

**ETAs**
- Pure driving time. No rest or hours-of-service breaks, fuel stops, or live or time-of-day traffic.

**Weather**
- One provider (Open-Meteo), model forecasts rather than observations. No official weather alerts.
- Locations are snapped to a 0.1° grid (about 7 miles) and the nearest forecast hour is used. Hourly precipitation values are treated as in/hr rates.
- Wind is 10 m sustained speed by default; gusts can matter more for trucks (see assumption 5).
- Forecasts cover 16 days; the heatmap covers 48 hours after departure.

**Risk scoring**
- Risk is estimated from **point samples**. Conditions between checkpoints are unknown, and each checkpoint's value is applied to the road halfway to its neighbours. On long routes the spacing is 50 miles.
- The ranking is strictly lexicographic, as the brief states, so a tiny difference in Severe miles outweighs a large difference in travel time.

**Free-tier infrastructure**
- **Open-Meteo's free tier limits calls per IP address.** Render's free instances share outbound IPs, so the daily quota can run out because of other apps. This was observed (HTTP 429). It is mitigated by batching, caching, prefetching and serving stale forecasts, but a **cold server with an exhausted shared IP can still fail**. The app then shows a "temporarily unavailable, try again" message.
- The weather cache is **in memory**. It is lost whenever the free instance sleeps or restarts, and it is not shared between processes.
- Cold starts take up to a minute after idle time.
- API throttling is 120 requests per minute per IP, and on a shared proxy all visitors may count as one IP.

**Frontend and security**
- The Mapbox token in the frontend is public by design (anyone can read it from the browser). It should be restricted to the production URL, and rotated after the assessment.
- Needs WebGL. The app shows an explanatory message if the map can't load.
- Units are US only (mph, inches, pounds, miles).
- No saved trips, accounts or offline support. Tested on a phone browser and a desktop-width layout, not across every browser.
- No end-to-end browser tests and no formal accessibility audit of the map.

## Possible next steps

- **Truck-aware routing** (for example HERE) with vehicle restrictions.
- **Official alerts** (for example NWS) layered onto the forecast, and a second weather provider as a fallback.
- **A shared cache** (Redis) so forecasts survive restarts and multiple workers.
- **"Best time to leave"**: run the same analysis across several departure times.
- **Hours-of-service-aware ETAs** and traffic.
- **Finer sampling** around hazardous stretches, and a gust/sustained toggle in the UI.
- **Browser-level end-to-end tests** (for example Playwright).

---

## Credits

Weather data by [Open-Meteo.com](https://open-meteo.com/) under CC BY 4.0. Routing, geocoding and maps by [Mapbox](https://www.mapbox.com/). Built with Django REST Framework, React, Vite and Mapbox GL JS.
