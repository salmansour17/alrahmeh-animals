# Project Brief: Al-Rahmeh Association for Animals — Assignment 1 Rebuild

## Context

This is Assignment 1 for my Software Development & DevOps course (BCSAI, IE University). This is a real rebuild of a real NGO's website: [Al-Rahmeh Association for Animals](https://www.alrahmehforanimals.org/), a small Jordanian animal rescue I previously audited for another course. I'll hand the finished app back to them. Read the assignment PDF in full before writing any code — it governs grading directly.

**Deadline:** 2026-10-04 23:59

## Hard Technical Constraints (non-negotiable, from the assignment)

- Single process, single container. No microservices, no separate repos.
- Storage: SQLite, at one documented path (ideally under a `DATA_DIR` env var).
- Exactly one dependency manifest at the repo root.
- Do NOT write a Dockerfile, docker-compose.yml, or any `.github/workflows/` CI file — that's provided separately later in the course.
- No Terraform/Bicep/ARM or other IaC.
- No real deployment (no custom domain, no Render/Heroku). Must run locally only.
- No external managed database/cache/queue.
- Backend must be Python (this is what I'm assessed on and what I need to defend cold in the comprehension check). Frontend can be React + CSS, served by the same single process.
- Binds to `0.0.0.0`, reads port from an env var with a sane default, starts with one documented command, no interactive setup (`input()`, wizards, manual migrations), starts within a few seconds.

## Two Required Backend Feature Domains

Both must persist through SQLite, must be logically separable with a clear seam, and business logic must be unit-testable. No shared-DB dependency between them beyond referencing each other's IDs where needed.

1. **Animal intake & adoption tracking** — animal profiles (name, species, breed, intake date, medical/vaccination history), an adoption status state machine (`available → pending → adopted`, plus `fostering` given how central fostering is to this org's real model), and ideally a simple adopter-fit matching helper. This directly replaces the static, unmanaged pet listings on the real site.
2. **Donation & impact ledger** — donations logged internally against a purpose (medical fund / food fund / general), with the homepage's impact statistics computed live from this data. This is a direct fix for a real bug I found in my audit: the real site's stat counters ("More than 300 pets found homes...") are hardcoded, not computed from anything real.

## Professor's Feedback and How to Handle It

He said I could try integrating Stripe as the payment mechanism if time allows, "shouldn't be that hard." Treat this as an **optional stretch goal**, not core scope — do NOT let it block the core two domains or the 70% test coverage bar. If we do add it, it must run in Stripe's test/sandbox mode only (no real transactions, no production keys, fits under §7.6's allowance for "a public API your use case genuinely needs"). If we run out of time and skip it, that becomes a legitimate ADR-5 entry ("what we deliberately chose not to build, and why") — document it honestly either way, don't hide the decision.

## Content Must Match the Real Organization

Not generic placeholder content. Reference points from the live site:

- Real org name: Al-Rahmeh Association for Animals / جمعية الرحمة للرفق بالحيوانات
- Real core programs to reflect in the UI/copy: Adoption, Fostering, Donating, Volunteering (their four site sections)
- Bilingual identity (Arabic + English) — at minimum keep Arabic in the branding/header, doesn't need full i18n
- Real social presence: Facebook and Instagram (facebook.com/Rahmehforanimals, instagram.com/rahmehforanimals)
- Contact: admin@alrahmeh.org
- Real broken things from my audit that this rebuild should visibly fix:
  - Hardcoded/fake stat counters → replace with live-computed stats from the donation ledger
  - Buried/awkward donation flow → surface it properly
  - No real backend behind "Adopt Now" / "Foster Now" (currently just Google Forms) → replace with an actual adoption/foster workflow tied to animal records

## Course Scope So Far

Use this to guide code quality, not to force pattern-stuffing.

We've covered SOLID principles and code smells:
- Bloaters break SRP
- Change Preventers break OCP
- OO Abusers break LSP
- Dispensables break ISP
- Couplers break DIP

Refactor toward small single-purpose classes, abstract base classes over concrete dependencies, dependency injection at composition roots.

We've also covered creational/structural/behavioral design patterns: Singleton, Factory Method, Builder, Adapter, Proxy, Facade, Observer, Strategy, Command.

Apply these naturally where they fit — e.g., a `Repository`-style abstraction over SQLite access (DIP), a state-machine-like status transition for adoption (could reasonably use Strategy or just clean explicit logic), maybe Observer if a donation triggers a stat/notification update. **Don't force patterns that don't fit** — forced patterns read as worse code quality, not better, and I need to be able to explain every one cold at the comprehension check.

## Process Deliverables to Maintain As We Go (not at the end)

- **`ADR.md`** — exactly 5 entries, added incrementally across at least 3 distinct commit dates, in the exact format specified in the assignment (Context / Decision / Alternatives considered / Consequences). Required entries:
  1. Backend framework choice
  2. How the two domains stay independently modularizable
  3. SQLite schema decision
  4. Testing approach/coverage tradeoffs
  5. One thing deliberately not built
- **`AI_USAGE.md`** — a row per meaningful AI interaction (date/commit, tool, prompt, disposition, what changed, and — most important — an explanation in my own words of how the accepted code actually works). Keep this updated every session, not backfilled.
- **Tests** — pytest with ≥70% coverage on core business logic of both domains (not routing/framework glue). Report the coverage command and result in the README.

## Commit Plan

12+ commits total, spread across 6+ distinct calendar days, no single day over 40% of commits, real descriptive messages, pushed to GitHub. Deadline: 2026-10-04 23:59.

| Day | Date | Focus | Target commits |
|---|---|---|---|
| 1 | Sep 25 | Repo init, dependency manifest, project scaffold, README skeleton, ADR-1 (framework choice) | 2 |
| 2 | Sep 26 | SQLite schema design + migrations, ADR-3 draft (data model) | 1 |
| 3 | Sep 27 | Domain A (animals/adoption) models + core business logic | 2 |
| 4 | Sep 28 | Domain A unit tests | 1 |
| 5 | Sep 29 | Domain B (donations/ledger) models + core logic, ADR-2 (domain separation) | 2 |
| 6 | Sep 30 | Domain B unit tests, run coverage check | 1 |
| 7 | Oct 1 | React frontend scaffold, wire up to backend API, apply real NGO content/branding | 2 |
| 8 | Oct 2 | Stripe test-mode stretch attempt (time permitting) OR polish; fix the real audit issues (live stats, donation flow) | 1 |
| 9 | Oct 3 | ADR-4 (testing approach), ADR-5 (not built), finalize AI_USAGE.md, write report (§8: SDLC, architecture diagram, schema diagram, README) | 2 |
| 10 | Oct 4 | Final polish, verify §7 deployment contract end to end, submit | 1 |

That's 15 commits across 10 distinct days — comfortable margin above the 12-commit/6-day minimum, and no day exceeds 2 commits (well under the 40% cap).

## First Step

Read the full assignment PDF, then propose the SQLite schema for both domains before writing any code, so it can be sanity-checked against ADR-3 before building.
