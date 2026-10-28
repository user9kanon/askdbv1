# AskDB: One-Pager

A web app that lets business users ask a database questions in plain English.

## Who the users are
- **Executives and managers.** They want quick, high-level answers. They are not analysts and will not dig into the data themselves.

## What they ask
- **Mostly KPI lookups**: single-figure questions such as "What was revenue last quarter?" or "How many active customers do we have?"
- Every question stands alone; there are no follow-up questions.

## What they need to see
- **The headline number, plus a small chart or table** that shows how it was reached or how it has moved recently.

## What must never happen (all three are equally critical)
1. **A wrong number shown with confidence.** If the question is unclear or the app is unsure, it must ask or say so instead of guessing.
2. **Data changed.** The app is strictly read-only and must never insert, update or delete anything.
3. **Restricted data seen.** Users must only see figures they are allowed to see, such as their own division's numbers and no salaries unless permitted.

## Out of scope for the first version
- Follow-up conversation ("now break that down by region")
- Exporting or sharing answers (Excel, PDF, sending to colleagues)
- Forecasts, predictions or recommendations
- Support for every type of database (the first version targets one specific database)

## Open questions
- Should saved dashboards, pinned answers and scheduled reports be in v1 or later?
- Which database will the first version use?
- Who decides what each user is allowed to see (for example, by division or by role)?
