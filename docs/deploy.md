# Deployment

**Live:** <https://firms-harmonizer-612652227111.europe-west1.run.app>

FIRMS Harmonizer deploys as a single Docker container that serves the FastAPI backend and
the built React frontend from the same origin. The image is built from the repository
`Dockerfile` and runs on Google Cloud Run. Local releases bundle the real cube, accepted
detections and lookup tables when available. If the image has no real cube, start-up
downloads runtime data from the public Hugging Face dataset. Bundled releases avoid
Hugging Face download limits during cold starts.

## Stack and costs

| Piece | Service | Free allowance | Role |
| --- | --- | --- | --- |
| App hosting | Google Cloud Run, `europe-west1` | 2M requests, 180k vCPU-seconds and 360k GiB-seconds per month | Runs the container; scales to zero between visits |
| Container images | Artifact Registry | 0.5 GB storage | Holds the image; a cleanup policy keeps the two latest |
| Runtime data | Hugging Face dataset `andearlla/firms-harmonizer-data` | Free public storage | Cube, accepted detections and ignored lookup tables (about 90 MB) |
| Continuous deployment | GitHub Actions | 2,000 minutes per month on private repositories | Redeploys after `Verify` passes on `main` (once configured) |
| Cost guard | Cloud Billing budget | Free | Email alerts at 50%, 90% and 100% of 1 EUR |

The service runs with 2 GiB of memory, 1 vCPU, request-based CPU billing, at most two
instances and eight concurrent requests each. Measured peak memory is 1.34 GB (a full
Iberia analysis); idle memory is about 150 MB. Cloud Run bills only while requests are being
served, so hackathon traffic stays inside the free tier. Activating billing in this account
required a prepayment, which is kept as account credit.

### Why this stack

- **Hugging Face Docker Spaces now require a PRO subscription** on the free CPU tier; only
  static Spaces remain free. The dataset is still free and is used for the data.
- **Memory.** The app needs about 1.4 GB at peak, which rules out 512 MB free tiers
  (Render, Koyeb). Fly.io and Railway have no permanent free plan, and Vercel, Netlify and
  Cloudflare cannot run this Python backend.
- **One container, one origin.** No CORS configuration and no second service to keep in step.

### Trade-offs

- After a period without visitors the first request starts a new instance: about 10 s for
  start-up, plus the frontend download in the browser. Images without bundled data also
  need a dataset download, which can fail if Hugging Face rate-limits the request.
- Instances have no persistent disk, so the "Update through today" sync cannot keep new
  data. Publish a new dataset version instead (see below).

## Day-to-day operations

All commands run from the repository root with the project virtual environment and an
authenticated `gcloud` (`gcloud auth login`).

- **Redeploy the current checkout:**

  ```powershell
  firms-harmonizer\.venv\Scripts\python deploy\cloudrun.py --project firms-harmonizer-2026 deploy
  ```

- **Check the live service:** `... deploy\cloudrun.py --project firms-harmonizer-2026 status`
- **Publish new data** after rebuilding the cube (`python scripts/run_pipeline.py etl`). It
  needs a Hugging Face write token (`hf auth login`). Rebuild and redeploy bundled images
  to apply updated local data. Images without bundled data fetch the published dataset
  when a new instance starts.

  ```powershell
  firms-harmonizer\.venv\Scripts\python deploy\publish.py data --repo andearlla/firms-harmonizer-data
  ```

- **Logs:** Google Cloud console, Cloud Run, service `firms-harmonizer`, Logs tab.

## First-time setup (already done for this project)

```powershell
gcloud auth login
python deploy\cloudrun.py --project <project-id> setup --billing-account <billing-id>
python deploy\publish.py data --repo <hf-user>/firms-harmonizer-data
python deploy\cloudrun.py --project <project-id> deploy --data-repo <hf-user>/firms-harmonizer-data
```

`setup` creates the project, links billing, enables Cloud Run, Artifact Registry and budgets,
creates the image repository with its cleanup policy, and adds the 1 EUR budget alert.

## Enabling automatic redeploys

`.github/workflows/deploy-cloudrun.yml` stays inactive until a deploy identity exists. It uses
Workload Identity Federation, so no key is stored in GitHub. A project owner runs once:

```powershell
$P = "firms-harmonizer-2026"
$N = gcloud projects describe $P --format="value(projectNumber)"
$SA = "github-deployer@$P.iam.gserviceaccount.com"
gcloud services enable iam.googleapis.com iamcredentials.googleapis.com sts.googleapis.com --project=$P
gcloud iam service-accounts create github-deployer --project=$P
gcloud projects add-iam-policy-binding $P --member="serviceAccount:$SA" --role=roles/run.admin
gcloud projects add-iam-policy-binding $P --member="serviceAccount:$SA" --role=roles/artifactregistry.writer
gcloud iam service-accounts add-iam-policy-binding "$N-compute@developer.gserviceaccount.com" --project=$P --member="serviceAccount:$SA" --role=roles/iam.serviceAccountUser
gcloud iam workload-identity-pools create github --location=global --project=$P
gcloud iam workload-identity-pools providers create-oidc almenara --workload-identity-pool=github --location=global --project=$P --issuer-uri=https://token.actions.githubusercontent.com --attribute-mapping="google.subject=assertion.sub,attribute.repository=assertion.repository" --attribute-condition="assertion.repository=='AdamBourbahh/Almenara'"
gcloud iam service-accounts add-iam-policy-binding $SA --project=$P --role=roles/iam.workloadIdentityUser --member="principalSet://iam.googleapis.com/projects/$N/locations/global/workloadIdentityPools/github/attribute.repository/AdamBourbahh/Almenara"
```

Then, in GitHub under **Settings → Secrets and variables → Actions → Variables**, add
`GCP_PROJECT` (`firms-harmonizer-2026`), `GCP_WIF_PROVIDER`
(`projects/<number>/locations/global/workloadIdentityPools/github/providers/almenara`) and
`GCP_SERVICE_ACCOUNT` (`github-deployer@firms-harmonizer-2026.iam.gserviceaccount.com`).
Only workflows from `AdamBourbahh/Almenara` can use this identity.

## Running the container locally

```powershell
docker build -t firms-harmonizer .
docker run -p 7860:7860 -e DATA_REPO=andearlla/firms-harmonizer-data firms-harmonizer
```

Instead of `DATA_REPO`, mount a local `firms-harmonizer\data\processed` folder at
`/app/data/processed`. Then open <http://localhost:7860>.

## Configuration reference

| Variable | Default | Meaning |
| --- | --- | --- |
| `DATA_REPO` | unset | Hugging Face dataset downloaded into `data/` at start-up |
| `DATA_REVISION` | latest | Dataset branch, tag or commit to pin |
| `HF_TOKEN` | unset | Needed only for a private dataset |
| `COPILOT_OFFLINE` | `1` | `0` enables online model and search providers when a key is set |
| `COPILOT_PROVIDER` | `groq` | `gemini` or `groq` |
| `NRT_POLLING` | `0` | Background FIRMS polling; keep off on serverless hosting |
| `USE_SYNTHETIC_CUBE` | `0` | `1` serves the labelled synthetic demo cube instead of real data |
| `PORT` | `7860` | Listening port |
| `REQUEST_RATE_MULTIPLIER` | `1` | Scales the per-visitor request limits |

To enable the online Copilot, store a Gemini or Groq key in Secret Manager and pass it to
the service, then set `COPILOT_OFFLINE=0`. Without a real cube the container exits with an
explanation rather than serving synthetic data silently. Each visitor gets their own
rate-limit bucket because the server trusts the platform's forwarded client address.

## Hugging Face Space (optional, PRO)

With a Hugging Face PRO subscription the same image can run as a Docker Space:
`python deploy\publish.py space --repo <user>/firms-harmonizer --data-repo <user>/firms-harmonizer-data --wait`.
