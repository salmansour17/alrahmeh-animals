# Evidence: the donations table before migration 003 (2026-11-26)

The data that migration `003` will meet on Azure. §4.6 asks for a migration
that changes a table already holding data, shown before and after; this is
the "before".

Captured 2026-11-26 20:07 UTC, with the donations service on commit
`510ef58` and its database at 2 migrations (`001_init`, `002_health_probe`).

- `before-staff-donations-list.png`: the staff portal's "Latest donations",
  three offline donations recorded by staff on the live site that evening:
  25.000 JOD (medical fund), 65.000 JOD (food fund) and 255.000 JOD (medical
  fund).
- `before-donation-impact.json`: `GET /api/donations/impact` at the same
  time: 3 donations, 345.000 JOD raised, 1 animal helped by an earmarked
  gift.

From the donations service's log, the two donations recorded with the
earmark check working after the connection fix (PR #55), each in under the
check's 2-second deadline plus the insert:

```
20:04:47 POST /api/donations 503 2001ms   <- animals service still starting (cold start)
20:04:52 POST /api/donations 503 2001ms   <- same
20:06:10 POST /api/donations 201 1779ms
20:06:38 POST /api/donations 201 1771ms
```
