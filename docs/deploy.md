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
| Cost guard | Cloud Billing budget and the `budget-guard` function | Free | Email alerts at 50%, 90% and 100% of 1 EUR; public access closes automatically at 100% |

The service runs with 2 GiB of memory, 1 vCPU, request-based CPU billing, at most one
instance and eight concurrent requests. Measured peak memory is 1.34 GB (a full
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

## Automatic spending cut-off

A budget alert alone does not stop spending. The budget therefore also publishes to the
Pub/Sub topic `budget-alerts`, which triggers the `budget-guard` function
(`deploy/budget_guard/`). When the reported cost reaches the budget amount, the function
removes the public (`allUsers`) invoker binding from the service. Visitors then receive
HTTP 403 before any instance starts, so request-driven spending stops. Image storage in
Artifact Registry is not affected and keeps its small storage cost.

Billing data reaches budgets with a delay of several hours, so the cut-off is not
instantaneous; the single-instance cap bounds what can be spent in the meantime. The
cut-off was tested on 2026-11-15 with a simulated over-budget notification.

To reopen the service after a cut-off (raise the budget or wait for the next month first):

```powershell
gcloud run services add-iam-policy-binding firms-harmonizer --region=europe-west1 --project=firms-harmonizer-2026 --member=allUsers --role=roles/run.invoker
```

Any later deployment also reopens the service, because it deploys with public access.
A project owner installs the guard once:

```powershell
$P = "firms-harmonizer-2026"
$SA = "budget-guard@$P.iam.gserviceaccount.com"
gcloud services enable pubsub.googleapis.com cloudfunctions.googleapis.com cloudbuild.googleapis.com eventarc.googleapis.com --project=$P
gcloud pubsub topics create budget-alerts --project=$P
gcloud pubsub topics add-iam-policy-binding budget-alerts --project=$P --member="serviceAccount:billing-budget-alert@system.gserviceaccount.com" --role=roles/pubsub.publisher
gcloud iam service-accounts create budget-guard --project=$P
gcloud run services add-iam-policy-binding firms-harmonizer --region=europe-west1 --project=$P --member="serviceAccount:$SA" --role=roles/run.admin
gcloud functions deploy budget-guard --gen2 --project=$P --region=europe-west1 --runtime=python312 --source=deploy/budget_guard --entry-point=enforce_budget --trigger-topic=budget-alerts --service-account=$SA --set-env-vars="GUARD_PROJECT=$P,GUARD_REGION=europe-west1,GUARD_SERVICE=firms-harmonizer" --memory=256Mi --max-instances=1 --no-allow-unauthenticated
gcloud run services add-iam-policy-binding budget-guard --region=europe-west1 --project=$P --member="serviceAccount:$SA" --role=roles/run.invoker
gcloud billing budgets update <budget-id> --billing-project=$P --notifications-rule-pubsub-topic="projects/$P/topics/budget-alerts"
```

## Enabling automatic redeploys

`.github/workflows/deploy-cloudrun.yml` deploys successful `Verify` push runs on `main`. It uses
Workload Identity Federation, so no key is stored in GitHub. A project owner runs once:

```powershell
$P = "firms-harmonizer-2026"
$N = gcloud projects describe $P --format="value(projectNumber)"
$SA = "github-deployer@$P.iam.gserviceaccount.com"
gcloud services enable iam.googleapis.com iamcredentials.googleapis.com sts.googleapis.com --project=$P
gcloud iam service-accounts create github-deployer --project=$P
gcloud run services add-iam-policy-binding firms-harmonizer --region=europe-west1 --project=$P --member="serviceAccount:$SA" --role=roles/run.admin
gcloud artifacts repositories add-iam-policy-binding firms-harmonizer --location=europe-west1 --project=$P --member="serviceAccount:$SA" --role=roles/artifactregistry.writer
gcloud iam service-accounts add-iam-policy-binding "$N-compute@developer.gserviceaccount.com" --project=$P --member="serviceAccount:$SA" --role=roles/iam.serviceAccountUser
gcloud iam workload-identity-pools create github --location=global --project=$P
gcloud iam workload-identity-pools providers create-oidc almenara --workload-identity-pool=github --location=global --project=$P --issuer-uri=https://token.actions.githubusercontent.com --attribute-mapping="google.subject=assertion.sub,attribute.repository=assertion.repository" --attribute-condition="assertion.repository=='AdamBourbahh/Almenara' && assertion.ref=='refs/heads/main' && assertion.workflow_ref=='AdamBourbahh/Almenara/.github/workflows/deploy-cloudrun.yml@refs/heads/main'"
gcloud iam service-accounts add-iam-policy-binding $SA --project=$P --role=roles/iam.workloadIdentityUser --member="principalSet://iam.googleapis.com/projects/$N/locations/global/workloadIdentityPools/github/attribute.repository/AdamBourbahh/Almenara"
```

Then, in GitHub under **Settings → Secrets and variables → Actions → Variables**, add
`GCP_PROJECT` (`firms-harmonizer-2026`), `GCP_WIF_PROVIDER`
(`projects/<number>/locations/global/workloadIdentityPools/github/providers/almenara`) and
`GCP_SERVICE_ACCOUNT` (`github-deployer@firms-harmonizer-2026.iam.gserviceaccount.com`).
The deployed identity is restricted to this deployment workflow on `main` in
`AdamBourbahh/Almenara`. Pull-request verification runs cannot trigger deployment.
The runner downloads the published real dataset before building, so instances do not
depend on Hugging Face availability at cold start. Older commits are skipped when
main has advanced. Existing Gemini settings and Secret Manager references are preserved.

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
| `COPILOT_PROVIDER` | `gemini` | `gemini` or `groq` |
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


## Pinned runtime data in Artifact Registry

The active release uses the existing private image registry for runtime data.
`RUNTIME_DATA_IMAGE` in GitHub Actions pins the data-only image by SHA-256 digest.
The workflow copies its `/data` directory and verifies every published file checksum
before building the application. It preserves the original timestamp manifest.
This avoids cold-start downloads and does not require a Hugging Face write token.
When this variable is absent, the workflow retains the public Hugging Face download path.

After rebuilding and validating the real dataset, publish a new data version with:

```powershell
firms-harmonizer\.venv\Scripts\python deploy/runtime_data.py --image europe-west1-docker.pkg.dev/firms-harmonizer-2026/firms-harmonizer/runtime-data:<version>
```

Set `RUNTIME_DATA_IMAGE` to the resulting image digest before the next release.
The data-only context contains only the existing publisher's explicit runtime file
allowlist, its timestamp manifest and file checksums. It excludes environment files,
logs, development reports, raw CSVs and source code. Application code still comes
from the verified GitHub main commit; Gemini's secret reference remains in Cloud Run.
