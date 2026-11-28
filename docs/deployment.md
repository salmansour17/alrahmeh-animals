# Deployment to Azure

Every push to `main` deploys, through `.github/workflows/cd.yml`, with no
manual step. This page lists what that workflow expects, and the one-time setup
(the bootstrap) that has to exist before its first run. Nothing here contains a
password.

## How a deploy runs

1. `ci.yml`, `contracts.yml`, `terraform.yml`, `security.yml` and
   `scanners.yml` run on the pushed commit. If any fails, nothing is deployed.
2. The three images are built with `GIT_SHA=<commit>` and pushed to
   `ghcr.io/<owner>/alrahmeh-<service>:<commit>`.
3. `terraform apply` (in `infra/`) updates the Container Apps environment, the
   three Container Apps (with those image tags) and the SQL server.
4. The three databases are created if they do not exist yet: serverless,
   paused after 15 idle minutes, at most 1 GB each. Existing databases are
   left exactly as they are.
5. The website is built with a `config.js` holding the three services'
   addresses from Terraform, and uploaded to the storage account's `$web`
   container: `index.html` and `config.js` with `no-cache`, the hashed assets
   cached for a year.
6. Each service must answer `GET /health` with 200 and `"status": "ok"`
   within five minutes, or the run fails.

## GitHub secrets and variables

Repository Settings, Secrets and variables, Actions.

| Secret | What it is |
|---|---|
| `AZURE_CLIENT_ID` | Client ID of the managed identity `snsour-ieu2024-github` |
| `AZURE_TENANT_ID` | The Azure tenant (directory) ID |
| `AZURE_SUBSCRIPTION_ID` | The Azure for Students subscription ID |
| `SQL_ADMIN_PASSWORD` | Password of the SQL server's administrator login (`sqladmin`) |
| `ANIMALS_DB_PASSWORD` | Password of the `animals_app` user in the animals database |
| `DONATIONS_DB_PASSWORD` | Password of the `donations_app` user in the donations database |
| `ENQUIRIES_DB_PASSWORD` | Password of the `enquiries_app` user in the enquiries database |
| `ADMIN_PASSWORD` | The staff portal password |
| `STRIPE_SECRET_KEY` | Optional. Stripe test-mode key; without it card donations stay off |
| `STRIPE_WEBHOOK_SECRET` | Optional. Signing secret of the Stripe webhook endpoint |

The three database passwords go inside a connection string, so use **letters
and digits only** (8 or more, upper and lower case and a digit).

| Variable | Value |
|---|---|
| `PREFIX` | `snsour-ieu2024`: IE username with dots replaced by hyphens |
| `LOCATION` | `germanywestcentral`: one of the subscription's allowed regions |
| `SQL_LOCATION` | `spaincentral`: an allowed region where the subscription may create a SQL server (ADR-8) |
| `RESOURCE_GROUP` | `rg-snsour-ieu2024` |
| `UI_STORAGE` | `snsourieu2024ui`: the prefix without hyphens, then `ui` |

Terraform's state lives in the `tfstate` container of `UI_STORAGE`; the backend
settings are in `infra/main.tf` and the workflow passes the account and
resource group at `terraform init`.

## The bootstrap (once, by hand)

The walkthrough, in order, with what each step does, how to verify it and how
to tear it down, is in the README under "Deploying to Azure". The scripts are
in `infra/bootstrap/`: `01` to `05` in Bash for Azure Cloud Shell, and
`create-db-users.ps1` in PowerShell for the database users after the first
deploy.

After the bootstrap, only the pipeline changes anything in Azure.
