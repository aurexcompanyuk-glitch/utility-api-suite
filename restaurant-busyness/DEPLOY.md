# Putting the app online

The goal: a URL anyone can open, running your BestTime key. Pick one route.

You do **not** need a Google Maps key — see "About Google Maps" at the bottom.

---

## Route A — Render (free tier, no card, easiest)

1. Go to [render.com](https://render.com) and sign in with GitHub.
2. **New → Web Service**, then pick `utility-api-suite`.
3. Choose branch `claude/restaurant-busyness-app-8ldszx`.
4. Render reads `render.yaml` and fills in the settings. If it asks manually:
   - **Root directory:** `restaurant-busyness`
   - **Build:** `pip install -r requirements.txt`
   - **Start:** `uvicorn main:app --host 0.0.0.0 --port $PORT`
5. Open **Environment** and add:

   | Key | Value |
   |---|---|
   | `BESTTIME_API_KEY_PRIVATE` | your `pri_…` key |
   | `BESTTIME_API_KEY_PUBLIC` | your `pub_…` key |

6. **Create Web Service.** First build takes 2–4 minutes.

Your app is at `https://<name>.onrender.com`.

> Free instances sleep after ~15 minutes idle, so the first request afterwards
> takes ~30 seconds. Fine for testing and demos; upgrade when real people use it.

---

## Route B — Railway

1. [railway.app](https://railway.app) → **New Project → Deploy from GitHub repo**.
2. Pick the repo and the branch above.
3. **Settings → Root Directory:** `restaurant-busyness`.
4. **Variables:** add the two `BESTTIME_…` keys.
5. **Settings → Networking → Generate Domain** to get a public URL.

Railway detects the `Procfile` automatically.

---

## Route C — Docker (Fly.io, Cloud Run, your own server)

```bash
cd restaurant-busyness
docker build -t busy-or-not .
docker run -p 8000:8000 -e BESTTIME_API_KEY_PRIVATE=pri_... busy-or-not
```

Then open <http://localhost:8000>. Deploy the same image anywhere.

---

## Check it worked

Open `https://your-url/health`. You want:

```json
{ "status": "ok", "data_source": "besttime", "besttime": { "reachable": true } }
```

- `"data_source": "simulated"` → the key isn't reaching the app. Re-check the
  environment variable name and redeploy.
- `"reachable": false` → the key is set but BestTime rejected it. The `error`
  field says why (usually an invalid or out-of-credit key).

Then open the root URL and search a venue.

---

## Before real users

- [ ] **Rotate the key** if it has ever been pasted into a chat, commit, or screenshot.
- [ ] Set `ALLOW_SIMULATED_FALLBACK=false` so the app never quietly serves demo
      numbers as if they were real.
- [ ] Move check-ins and cached venues to a database — both currently live in
      memory and reset on every restart or redeploy.
- [ ] Watch your BestTime credits on `/health`. Raise `LIVE_CACHE_TTL` and
      `FORECAST_CACHE_TTL` if you're burning through them.
- [ ] Add rate limiting before you make the URL public — every request to your
      app can cost you a BestTime credit.

---

## About Google Maps

**You don't need a Google Maps key, and it won't give you busyness data.**

Google shows "popular times" in the Maps app, but it has never exposed that
through the Places API — there is no official field for popular times or live
busyness. That gap is exactly why BestTime.app exists. Buying a Maps key would
cost money and still leave you without the one thing this app is about.

Where Google Places *would* help later, once you have paying users:

| Want | Use |
|---|---|
| How busy a place is | **BestTime** (already wired up) |
| Type-ahead venue suggestions as the user types | Google Places Autocomplete |
| Real photos, reviews, phone numbers | Google Places Details |
| A map with pins | Google Maps JS SDK, or free Leaflet + OpenStreetMap |

None of those are needed to launch. BestTime's own venue search already finds
places, and place-name lookup already works through OpenStreetMap for free.

Add Google only when a specific feature demands it — and treat it as a second
paid dependency, billed per request like BestTime.
