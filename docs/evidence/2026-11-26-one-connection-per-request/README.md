# Evidence: a bug found on Azure, and the commit that fixed it (2026-11-26)

## The symptom

Staff recording a donation earmarked for an animal on the live site were
always refused with "Could not check the earmarked animal right now. Please
try again in a minute.", even with both services running. Donations without
an animal were recorded normally. Screenshot:
`../2026-11-25-first-deploy/earmark-check-timeout-during-cold-start.png`.

## Diagnosis, from the two services' logs (read with `az containerapp logs show`)

The donations service gave up on every earmark check at its 2-second
deadline:

```
09:52:59 stdout POST /api/donations 503 2001ms
09:52:59 stderr WARNING donations.animals_client: Animals service unavailable while checking animal 1: no answer before the deadline
09:53:14 stdout POST /api/donations 503 2001ms
09:54:56 stdout POST /api/donations 503 2006ms
09:55:17 stdout POST /api/donations 503 2002ms
09:55:45 stdout POST /api/donations 201 593ms        <- a donation with no animal: no check, recorded
```

At the same moments the animals service was warm and healthy, but each
lookup of the animal took about 3.4 seconds:

```
09:52:51 stdout GET /health 200 632ms
09:53:01 stdout GET /api/animals/1 200 3483ms
09:53:15 stdout GET /api/animals/1 200 3432ms
09:54:57 stdout GET /api/animals/1 200 3448ms
09:55:19 stdout GET /api/animals/1 200 3431ms
```

Cause: `GET /api/animals/<id>` runs four units of work (the animal, its
vaccinations, its profile, its photo's version) and each opened its own
database connection. On a laptop that costs nothing; on Azure every
connection is a TLS login from the Container Apps in `germanywestcentral` to
the database in `spaincentral`. Four logins added up to about 3.4 s, past the
2-second deadline (ADR-6). The tests never showed it, because the test
database is on the same machine.

## The fix

PR #55, commit `fix: one database connection per request, not one per query`:
each request opens at most one connection, shared by its units of work (each
still its own transaction), and closes it when the request ends. Deployed by
[CD 45886321756](https://github.com/salmansour17/alrahmeh-animals/actions/runs/45886321756)
(commit `510ef58`).

## After, on Azure (2026-11-26 19:52 UTC)

Server-side, from the animals service's log:

```
19:52:29 stdout GET /api/animals/1 200 1139ms
19:52:31 stdout GET /api/animals/1 200 1150ms
19:52:32 stdout GET /api/animals/1 200 1146ms
19:52:34 stdout GET /api/animals/1 200 1134ms
19:52:38 stdout GET /api/animals 200 641ms
```

| Request | Before | After |
|---|---|---|
| `GET /api/animals/1` (what the earmark check calls), server-side | 3.43-3.48 s | 1.13-1.15 s |
| the same, measured from outside Azure | 3.6-3.9 s | 1.31-1.35 s |
| `GET /api/animals` (the list), from outside | 1.27 s | 0.82 s |

The lookup now ends well inside the 2-second deadline, with about 0.85 s to
spare.
