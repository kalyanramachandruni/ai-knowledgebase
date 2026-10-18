<!-- OPENWIKI:START -->

## OpenWiki

@AGENTS.md

<!-- OPENWIKI:END -->

## Spec-driven development

Features are built from spec files in `specs/`. The workflow:

1. Spec is written in `specs/pending/` using `specs/TEMPLATE.md`
2. When asked to implement a spec (e.g. "implement specs/pending/001-foo.md"):
   - Read the spec file fully before writing any code
   - Move it to `specs/in-progress/` at the start
   - Implement all layers described (DB migration → backend → frontend) in order
   - Check off each acceptance criterion as it is satisfied
   - Move the file to `specs/done/` when all criteria are met
3. Do not implement anything not described in the spec. Scope questions go back to the user before coding starts.
4. If a spec is ambiguous or contradicts existing code, surface the conflict and ask before proceeding.

@specs/TEMPLATE.md
