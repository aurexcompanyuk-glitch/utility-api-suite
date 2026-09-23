# Installed skills

Design skills from https://github.com/Leonxlnx/taste-skill (MIT, by
leonxlnx), installed 2026-09-11.

Only the `skills/` directory was taken — the upstream repo's assets and
research folders are not vendored here.

Each folder is named after the skill's own `name:` frontmatter, which is
what Claude Code registers, not the upstream directory name.

Reviewed before installing: no code execution, no credential or network
access, no instructions that conflict with this project. They are design
guidance documents.

## From open-design (added 2026-09-22)

Four skills from https://github.com/nexu-io/open-design (Apache 2.0):
`web-design-guidelines` (Vercel's Web Interface Guidelines, aimed at
product UI), `frontend-design`, `impeccable-design-polish` and
`design-review`.

That repo is a whole desktop application carrying 537 skills; only these
four were taken. Its `ui-ux-pro-max` skill is a catalog stub upstream —
it carries no templates or workflow — so it was not installed.

## ui-ux-pro-max (added 2026-09-23)

The real skill from https://github.com/nextlevelbuilder/ui-ux-pro-max-skill
(MIT) — not the catalog stub that ships inside open-design, which carries
no templates, data or search workflow.

Includes its searchable data (styles, product palettes, typography,
colour, icons, motion, charts, UX guidelines), the reference rule files
and `scripts/search.py`. Upstream test fixtures were dropped; nothing
else was trimmed.

Query it with:
  python3 .claude/skills/ui-ux-pro-max/scripts/search.py "<query>" --domain <ux|style|color|typography|product|icons|chart|gsap>
