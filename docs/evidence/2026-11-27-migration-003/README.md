# Evidence: migration 003 on Azure, after

The "after" half of §4.6: migration `003_ledger_reversals.sql` changed the
`donations` table on Azure while it already held three gifts. The "before"
half is in `../2026-11-26-before-migration-003/`.

The migration ran on 2026-11-26 at 21:52 UTC, in the deploy of PR #56. The
screenshots and the data below were captured by hand on the live site on
2026-11-28, around 15:50 UTC.

## 1. The migration ran on Azure

[CD run 45900780857](https://github.com/salmansour17/alrahmeh-animals/actions/runs/45900780857),
job `deploy to Azure`, step **Show each service's start-up log**:

```
donations migrations:
2026-11-26T21:52:57.681908026+00:00 stderr INFO __main__: Applied migration 003_ledger_reversals.sql to snsour-ieu2024-donations-db
```

The animals and enquiries databases are "up to date" (3 and 2 migrations):
they had nothing new. `migration-log-line.png` is a screenshot of those lines.

## 2. The rows already there were kept, and changed in place

`after-migration-list.png`: the staff portal's "Latest donations" after the
migration. The same three gifts as `before-staff-donations-list.png`
(25.000 JOD medical fund, 65.000 JOD food fund and 255.000 JOD medical fund,
the last two earmarked for Rocky), now numbered #1 to #3 and each reversible.
They became `kind = gift` through the column's default, with no `UPDATE`: the
append-only trigger from `001` was never switched off.

## 3. A correction on the live site

`after-reversal-list.png`: the 255.000 JOD gift (#3) reversed from the staff
portal with the reason "recorded twice by mistake". A new row, #4, is
labelled **Reversal** of #3 and shows the reason; #3 is struck through and
labelled **Reversed** by #4; neither can be reversed again. Nothing was edited
or deleted: the correction is a new row.

## 4. The figures follow

`after-reversal-homepage-counters.png` and `after-donation-impact.json`
(`GET /api/donations/impact`):

| | Before (2026-11-26) | After (2026-11-28) |
|---|---|---|
| Migrations on the donations database | 2 | 3 |
| Rows in `donations` | 3 gifts | the same 3, now `kind = gift`, plus 1 reversal |
| Total raised on the homepage | 345.000 JOD | 90.000 JOD |
| Medical fund | 280.000 JOD | 25.000 JOD |
| Food fund | 65.000 JOD | 65.000 JOD |
| Gifts counted | 3 | 2 |
| Animals helped by an earmarked gift | 1 (Rocky) | 1 (Rocky, through the 65.000 JOD gift that stands) |

A reversal is a ledger entry only: it does not refund a card payment at the
payment provider.
