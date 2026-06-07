# A.R.G.U.S. — backend deploy guide

The Python backend (`scanner.py` + `argus_ledger.py`) runs as a Flask web
service. This guide walks through deploying it on Render and wiring the
React frontend on Vercel to call it.

## 1. Deploy `scanner.py` to Render

1. Push `main` to GitHub (already done if you got this far).
2. Open https://dashboard.render.com → **New +** → **Web Service**.
3. Connect the `mitsugue/argus` repo.
4. Render will pick up `render.yaml` automatically. Confirm:
   - **Runtime**: Python
   - **Build**: `pip install -r requirements.txt`
   - **Start**: `python scanner.py`
   - **Plan**: Free
5. Add environment variables (Render dashboard → Environment):
   - `JQUANTS_API_KEY`
   - `GEMINI_API_KEY`
   - `ANTHROPIC_API_KEY`
   - `FINNHUB_API_KEY` (optional)
   - `NEWS_API_KEY` (optional)
   - `X_API_BEARER_TOKEN` (optional)
   - `EDINET_API_KEY` (optional)
   - `ARGUS_LEDGER_PATH=data/predictions.jsonl` (already in render.yaml)
6. Click **Create Web Service**. First build ≈ 2–3 min.

Render gives you a URL like `https://argus-backend.onrender.com`. Note it.

### Persistent ledger (recommended)

Free Render disks are ephemeral — predictions reset on each deploy. To
keep the calibration history:

1. Render dashboard → your service → **Disks** → **Add Disk**
   - Name: `argus-data`, Mount path: `/var/data`, Size: 1 GB
2. Add env var `ARGUS_LEDGER_PATH=/var/data/predictions.jsonl` (overrides
   the one in render.yaml).

Cost: $1/mo. Without it, calibration is a 30-day rolling sample of
whatever has run since the last deploy.

## 2. Point the Vercel frontend at it

1. Vercel dashboard → your `argus` project → **Settings** →
   **Environment Variables** → add:
   - **Key**: `VITE_ARGUS_BACKEND_URL`
   - **Value**: `https://argus-backend.onrender.com` (the URL from step 1)
   - **Environment**: Production + Preview
2. Trigger a redeploy (Deployments → ... → Redeploy).

The frontend will call `${VITE_ARGUS_BACKEND_URL}/api/argus/calibration`
once Phase 5 lands. CORS is already configured on the backend for
`*.vercel.app` and `localhost`.

## 3. Smoke test

After Render finishes deploying, hit these from your browser:

```
https://argus-backend.onrender.com/api/argus/calibration
https://argus-backend.onrender.com/api/argus/picks/today
https://argus-backend.onrender.com/api/argus/ledger/recent
```

Expected:
- `calibration` returns `{ windowDays: 30, resolvedCount: 0, ... }` until
  the scanner has actually run a few times.
- `picks/today` returns `{ phase: 0, picks: [] }` before the first scan.
- `ledger/recent` returns `{ entries: [] }`.

## 4. Trigger the first scan

The scheduler in `scanner.py` runs `phase1..phase4` daily at JST 08:30
on weekdays. To kick a one-off:

```bash
curl -X POST https://argus-backend.onrender.com/api/run
```

Wait ~5–10 minutes for phases to complete. After phase 4 finishes,
`/api/argus/calibration` will show `pendingCount: 3` (today's picks
waiting on resolution). After phase 5 (next morning's open), they
resolve and `hitRate` starts populating.

## 5. Local dev

```bash
# Backend (in repo root)
pip install -r requirements.txt
export JQUANTS_API_KEY=...
# ... other env vars from .env if you have one
python scanner.py        # serves on http://127.0.0.1:8080

# Frontend (in web/)
echo "VITE_ARGUS_BACKEND_URL=http://localhost:8080" > .env.local
npm run dev              # serves on http://127.0.0.1:5173
```

The frontend will hit the local backend; CORS already allows localhost.
