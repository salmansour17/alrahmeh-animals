# Evidence: migration 003 on Azure, after (to collect on 2026-11-27)

The "after" half of §4.6: migration `003_ledger_reversals.sql` changing the
`donations` table that already holds the three gifts recorded on 2026-11-26.
The "before" half is in `../2026-11-26-before-migration-003/`.

This file is a checklist. Nothing below has been captured yet: fill in each
item from the live site and the Actions log, and replace this paragraph with
the date and time you did.

## 1. The migration log line

After the pull request is merged, open the CD run it starts (Actions, "CD",
the run for the merge commit). In the `deploy to Azure` job, the last step is
**Show each service's start-up log**. Below the collapsed groups it prints,
for the donations service:

```
donations migrations:
INFO migrate: Applied migration 003_ledger_reversals.sql to snsour-ieu2024-donations-db
```

- [ ] CD run link: ...
- [ ] `migration-log-line.png`: a screenshot of that line in the Actions log.

If the step shows a `::warning::` instead (the container started before the
log window), expand the donations group and search for `Applied migration`;
if it is not there either, read the log by hand while the app is awake:

```powershell
docker run --rm -v alrahmeh-azure-cli:/root/.azure mcr.microsoft.com/azure-cli:latest az containerapp logs show --subscription "Azure for Students" -g rg-snsour-ieu2024 -n snsour-ieu2024-donations --type console --tail 300 --format text
```

## 2. The same rows, after the migration

Open the staff portal (https://snsourieu2024ui.z1.web.core.windows.net/staff,
"Record offline"). The first load may take up to a minute while the apps and
databases wake; if a message asks you to try again, wait and reload.

- [ ] `after-migration-list.png`: "Latest donations" showing the same three
  gifts as `before-staff-donations-list.png` (25.000, 65.000, 255.000 JOD),
  now numbered (#1, #2, ...) and each with a **Reverse** button. This shows
  the existing rows were kept and became gifts, with no edit to any of them.

## 3. A reversal on the live site

Reverse the 255.000 JOD gift (the "recorded by mistake" case):

1. Click **Reverse** on that row.
2. Type a reason, for example `Recorded twice by mistake`.
3. Click **Reverse donation**.

- [ ] `after-reversal-list.png`: the new row labelled **Reversal** of #N with
  the reason, and the 255.000 JOD gift struck through and labelled
  **Reversed** by #M. Neither has a Reverse button.
- [ ] `after-reversal-homepage-counters.png`: the homepage counters, now
  **90.000 JOD** raised instead of 345.000 (and still 1 animal helped, by the
  earmarked 25.000 JOD gift).
- [ ] `after-donation-impact.json`: open
  https://snsour-ieu2024-donations.politewater-5e265943.germanywestcentral.azurecontainerapps.io/api/donations/impact
  and save the page. Expected: `"donation_count": 2`, total `"90.000"`.

## 4. Optional: the rules, live

- [ ] `reverse-twice-refused.png`: try reversing the same gift again from
  another tab that still shows the Reverse button. Expected message: "donation
  N has already been reversed" (409).

## What this shows

| | Before (2026-11-26) | After |
|---|---|---|
| Migrations on the donations database | 2 | 3 |
| Rows in `donations` | 3 gifts | the same 3, now `kind = gift`, plus 1 reversal |
| Total raised on the homepage | 345.000 JOD | 90.000 JOD |
| Gifts counted | 3 | 2 |

A reversal is a ledger entry only: it does not refund a card payment at the
payment provider.
