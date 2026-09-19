# GitHub decision tracker

The canonical map is [Define the Callimachus meeting archive](https://github.com/SaltyThePolo/callimachus/issues/1). Decisions and resolutions live in GitHub Issues; this directory does not duplicate their state.

## Wayfinding operations

- Map: issue labelled `wayfinder:map`.
- Tickets: native sub-issues of the map, labelled `wayfinder:research`, `wayfinder:grilling`, `wayfinder:prototype`, or `wayfinder:task`.
- Claim: assign the ticket to the developer driving it before work begins. Initial developer: `SaltyThePolo`.
- Blocking: use GitHub's native issue dependencies, after both issues exist.
- Frontier: list the map's open sub-issues, exclude assigned tickets, then exclude those with open blocking issues; order by creation time. Do not rely on labels alone to establish dependencies.
- Resolution: post a resolution comment with named asset links, close the ticket, then append a named link and one-line gist to the map's Decisions so far.
- Research: keep the findings in `docs/research/`, capture the research context on a `research/<name>` branch, and link it from the ticket.

Use issue titles as link text in user-facing discussion. Preserve concurrent changes and keep open-ticket lists out of the map body.
