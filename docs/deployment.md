# Deployment to Azure

Every push to `main` deploys, through `.github/workflows/cd.yml`, with no
manual step. This page lists what that workflow expects, and the one-time setup
(the bootstrap) that has to exist before its first run. Nothing here contains a
password; each `<...>` is filled in when the setup is done.

## How a deploy runs

1. `ci.yml`, `contracts.yml` and `terraform.yml` run on the pushed commit. If
   any fails, nothing is deployed.
2. The three images are built with `GIT_SHA=<commit>` and pushed to
   `ghcr.io/<owner>/alrahmeh-<service>:<commit>`.
3. `terraform apply` (in `infra/`) updates the Container Apps environment, the
   three Container Apps (with those image tags) and the SQL server.
4. The three databases are created on Azure SQL's free offer if they do not
   exist yet. Existing databases are left exactly as they are.
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
| `AZURE_CLIENT_ID` | Client ID of the managed identity `<PREFIX>-github` |
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
| `PREFIX` | `<PREFIX>`: IE username with dots replaced by hyphens |
| `LOCATION` | `<REGION>`: one of the subscription's allowed regions |
| `SQL_LOCATION` | `<SQL_REGION>`: an allowed region where the free offer exists (not `spaincentral`) |
| `RESOURCE_GROUP` | `rg-<PREFIX>` |
| `UI_STORAGE` | `<PREFIXNH>ui`: the prefix without hyphens, then `ui` |

Terraform's state lives in the `tfstate` container of `UI_STORAGE`; the backend
settings are in `infra/main.tf` and the workflow passes the account and
resource group at `terraform init`.

## The bootstrap (once, by hand)

Done once in Azure Cloud Shell (Bash), which has `az`, `gh` and `sqlcmd`. The
exact commands will be recorded here when they are run; this is the order and
what each step is for.

1. **Subscription and region.** Select the Azure for Students subscription and
   list its allowed regions (policy assignment "Allowed resource deployment
   regions").
2. **Providers and resource group.** Register `Microsoft.App`,
   `Microsoft.OperationalInsights`, `Microsoft.Sql`, `Microsoft.Storage` and
   `Microsoft.ManagedIdentity`, then create `rg-<PREFIX>`. Terraform registers
   nothing itself (`resource_provider_registrations = "none"`), because the
   pipeline's identity is only Contributor on this one resource group.
3. **Storage account.** `<PREFIXNH>ui`, StorageV2, Standard_LRS, in the
   resource group. Enable the static website with `index.html` as both the
   index and the 404 document (so React Router's links work), and create a
   private container `tfstate` for Terraform's state.
4. **The pipeline's identity.** A user-assigned managed identity
   `<PREFIX>-github`, Contributor on `rg-<PREFIX>` only, with a federated
   credential for `repo:<OWNER>/<REPO>:ref:refs/heads/main` (issuer
   `https://token.actions.githubusercontent.com`, audience
   `api://AzureADTokenExchange`). Register the numeric-ID form of the subject
   too if GitHub sends it.
5. **GitHub secrets and variables**, as in the tables above.
6. **Reader access** on `rg-<PREFIX>` for the two professors.
7. **First deploy.** Push to `main`. It is expected to fail twice before it
   passes:
   - pulling the images fails until each GHCR package
     (`alrahmeh-animals`, `alrahmeh-donations`, `alrahmeh-enquiries`) is made
     public in its GitHub package settings;
   - the services cannot log in until their database users exist (step 8),
     so the health check times out.
8. **The database users**, once the run has created the databases. Open the
   SQL server's firewall to your own IP, then in each database, as
   `sqladmin`:

   ```sql
   -- in <PREFIX>-animals-db (and the same with donations_app, enquiries_app
   -- in the other two databases), with the password from the GitHub secret
   CREATE USER animals_app WITH PASSWORD = '<ANIMALS_DB_PASSWORD>';
   ALTER ROLE db_ddladmin ADD MEMBER animals_app;
   ALTER ROLE db_datareader ADD MEMBER animals_app;
   ALTER ROLE db_datawriter ADD MEMBER animals_app;
   ```

   These are contained users: they exist inside one database and can reach
   nothing else. Remove your IP from the firewall again, then re-run the
   failed deploy.

After the bootstrap, only the pipeline changes anything in Azure.

## Placeholders to fill in

| Placeholder | Where |
|---|---|
| `<PREFIX>`, `<PREFIXNH>` | `system.yaml`, this page, the GitHub variables |
| `<STUDENT>` | `system.yaml` |
| `<N>` | `system.yaml` `public_url`: the zone number in the static website address |
| `<REGION>`, `<SQL_REGION>` | GitHub variables `LOCATION`, `SQL_LOCATION` |
| `<OWNER>/<REPO>` | the federated credential's subject (`salmansour17/alrahmeh-animals`) |
