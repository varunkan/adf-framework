# End-to-end deployment guide

Deploy the **production split stack**:

| Component | Platform | URL pattern |
|-----------|----------|-------------|
| Next.js UI | **Vercel** | `https://*.vercel.app` |
| FastAPI API | **Railway** (Docker) | `https://*.up.railway.app` |
| Postgres | Railway plugin | internal `DATABASE_URL` |

Alternative backend: **Render** via [`render.yaml`](render.yaml) (Blueprint).

---

## Option A — One script (local CLI)

### 1. Create accounts & tokens

1. [Railway](https://railway.com) → Account → **Tokens** → create token  
   ```bash
   export RAILWAY_TOKEN=your_token
   ```

2. [Vercel](https://vercel.com) → Account → **Tokens**  
   ```bash
   vercel login
   export VERCEL_TOKEN=your_token   # optional if logged in via CLI
   ```

### 2. Run deploy

```bash
cd adf-framework/apps/ands-submission-portal/production
chmod +x scripts/deploy-e2e.sh
./scripts/deploy-e2e.sh
```

The script will:

- Create/link a Railway project + Postgres
- Deploy the API Docker image
- Health-check `/api/health`
- Deploy the Next.js app to Vercel with `NEXT_PUBLIC_API_URL` set

### 3. Verify

```bash
# Replace with your URLs from script output
curl https://YOUR-API.up.railway.app/api/health
open https://YOUR-APP.vercel.app
```

Use **Intake** → Validate → Submit, then **Submissions** dashboard.

---

## Option B — GitHub Actions (CI deploy)

### Required secrets (repo → Settings → Secrets → Actions)

Create environment **`ands-portal`** (optional but recommended).

| Secret | Description |
|--------|-------------|
| `RAILWAY_TOKEN` | Railway account or project token |
| `RAILWAY_API_SERVICE_ID` | Service ID for the API (Railway dashboard → service → Settings) |
| `VERCEL_TOKEN` | Vercel token |
| `VERCEL_ORG_ID` | From `vercel link` → `.vercel/project.json` |
| `VERCEL_PROJECT_ID` | From `.vercel/project.json` |
| `ANDS_API_PUBLIC_URL` | Public API base, e.g. `https://ands-portal-api-production.up.railway.app` |

### First-time Railway setup

```bash
cd adf-framework/apps/ands-submission-portal
npx @railway/cli login
npx @railway/cli init -n ands-portal
npx @railway/cli add --database postgres
npx @railway/cli up --detach
npx @railway/cli domain   # note public URL → ANDS_API_PUBLIC_URL
```

Copy the **service ID** from Railway → API service → Settings.

### First-time Vercel setup

```bash
cd production/frontend
vercel link
# note orgId + projectId from .vercel/project.json
vercel env add NEXT_PUBLIC_API_URL production
# paste ANDS_API_PUBLIC_URL
```

### Trigger deploy

```bash
gh workflow run deploy-ands-portal.yml
# or push to main/adf-framework with production/ changes
```

---

## Option C — Render Blueprint

1. Push repo to GitHub.
2. [Render Dashboard](https://dashboard.render.com) → **New** → **Blueprint**.
3. Connect repo; point blueprint to `production/render.yaml`.
4. Adjust `rootDir` if your repo layout differs.
5. After deploy, set `CORS_ORIGINS` on the API service to your Vercel URL.
6. Deploy Vercel frontend with `NEXT_PUBLIC_API_URL` = Render API URL.

---

## Environment variables (API)

| Variable | Default | Notes |
|----------|---------|-------|
| `DATABASE_URL` | — | Auto from Railway/Render Postgres |
| `PORT` | `8080` | Set by platform |
| `CORS_ORIGINS` | `http://localhost:3000` | Add custom Vercel domain |
| `CORS_ALLOW_VERCEL_PREVIEWS` | `true` | Allows `*.vercel.app` |
| `S3_ENABLED` | `true` | Set `false` until S3/MinIO configured |
| `ESG_MODE` | `mock` | `test` when FDA ESG credentials ready |

---

## Troubleshooting

| Issue | Fix |
|-------|-----|
| UI shows API unreachable | Check `NEXT_PUBLIC_API_URL` on Vercel (redeploy after change) |
| CORS error in browser | Add your Vercel URL to `CORS_ORIGINS` on Railway |
| API crash on start | Ensure Postgres plugin linked; check `railway logs` |
| `RAILWAY_TOKEN` invalid | Regenerate at railway.com/account/tokens |

---

## Monolith fallback (local demo)

The original stdlib server is unchanged:

```bash
cd adf-framework/apps/ands-submission-portal
python3 server.py
```

Production stack lives under `production/` only.
