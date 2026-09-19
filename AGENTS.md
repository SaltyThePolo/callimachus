# Shared contributor instructions

## Docker distribution

Use source-based Compose builds (`docker compose up --build -d`). The user withdrew prebuilt image distribution: keep Docker Hub login, registry publishing, and recurring CI/release image builds out of this project. Container validation belongs to the implementation checks. See the latest requirements in the Docker implementation ticket.

## Commit messages

Every agent and human contributor must use Conventional Commits for new commits:

```text
type(optional-scope): concise description of the change
```

Use lowercase types: `feat`, `fix`, `docs`, `style`, `refactor`, `perf`, `test`, `build`, `ci`, `chore`, or `revert`. Write descriptions in English, using a concrete action; describe the change rather than copying a ticket title or saying "updates". Scope is optional and should name the affected area. Mark breaking changes with `!` before the colon and explain their impact in the body.

Examples:

```text
feat(archive): store current meeting text in readable folders
fix(drive): respect deleted meeting folders during sync
docs: explain Google OAuth setup
ci: validate commit message format
```

Keep one coherent change per commit. Add a short body when the reason or trade-off is not obvious, and include relevant validation for substantive changes. Reference related issues in a footer; use `Closes` only when their acceptance criteria are actually satisfied. Never put tokens, credentials, or private meeting content in a commit message.

The Commit messages workflow checks new non-merge commits on pushes and all proposed non-merge commits on pull requests. On initial branch creation, it checks the tip commit. Existing published history is left unchanged. Avoid rewriting pushed commits merely to adopt this convention.

CI checks syntax; choosing an accurate type and useful description remains the contributor's responsibility. A failing check does not prevent direct pushes unless repository protection is configured.
