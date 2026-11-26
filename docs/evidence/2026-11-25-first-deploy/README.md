# Evidence: first deploys to Azure (2026-11-25)

The state of the live system after the first deploy, before any migration
changes a table on Azure. The "after" evidence for the §4.6 migration will be
compared with the `before-*` files here.

## The two deploy runs

| Run | Commit | What it shows | Result |
|---|---|---|---|
| [CD 45714506460](https://github.com/salmansour17/alrahmeh-animals/actions/runs/45714506460) | `4e9c470`, merge of PR #33 | first successful deploy to Azure: the services started on empty databases, ran their migrations at start-up and loaded the sample animals | success |
| [CD 45716078577](https://github.com/salmansour17/alrahmeh-animals/actions/runs/45716078577) | `a8d3a8f`, merge of PR #34 | first deploy gated on `security.yml`: Trivy (images and config), gitleaks, Conftest | success |

- `cd-run-45714506460-jobs.txt`, `cd-run-45716078577-jobs.txt`: every job and its result.
- `cd-run-45714506460-deploy-excerpt.txt`: the deploy job's key lines, with
  timestamps: Terraform's summary (0 added, 4 changed, 0 destroyed), the three
  databases found and left untouched, the service addresses written into the
  website's `config.js`, and each service's `/health` answer.

## The live system, captured 2026-11-25 23:23 UTC

- Website: https://snsourieu2024ui.z1.web.core.windows.net
- `health.txt`: each service's `GET /health`, `{"status":"ok","db":"ok"}`
  with the deployed commit as `version`.
- `before-homepage-counters.png`: the homepage counters, computed live from
  the two services' data: 1 animal home, 0.000 JOD raised, 0 animals helped by
  earmarked gifts.
- `before-animals-page.jpg`: the six animals from the animals database.
- `before-animals.json`: `GET /api/animals` (6 animals).
- `before-animal-stats.json`: `GET /api/animals/stats`: 4 available,
  1 fostering, 1 adopted.
- `before-donation-impact.json`: `GET /api/donations/impact`: no donations
  yet.

- `earmark-check-timeout-during-cold-start.png` (2026-11-26, morning): staff
  recording a 25 JOD donation earmarked for Luna while the animals service was
  scaled to zero. The earmark check could not get an answer within its
  2-second deadline, so the donations service refused to write to the
  append-only ledger and asked staff to retry ("None yet" below the form: no
  row was written). This is the designed failure for staff in ADR-6, met in
  practice exactly as ADR-8 expected.

Checked at the same time, not saved as files: plain HTTP is redirected to
HTTPS (301); a browser request from the website's origin gets an
`Access-Control-Allow-Origin` header and one from any other origin does not.

## Where it runs

- Container Apps in `germanywestcentral`, scaled 0 to 1.
- SQL server `snsour-ieu2024-sql` in `spaincentral` with three serverless
  databases (0.5 to 1 vCore, paused after 15 idle minutes, at most 1 GB), not
  on the free offer (ADR-8, amendment of 2026-11-25).
