# Lucian UX/UI Prompt adaptations

- Official site: https://lucianlabs.dev/uxui-prompt/
- Upstream repository: https://github.com/Seokwoooo/lucian-uxui
- License checked 2026-11-16 against the upstream primary source:
  https://raw.githubusercontent.com/Seokwoooo/lucian-uxui/main/LICENSE
- Upstream copyright: Copyright (c) 2026 Seokwoooo.
- The full MIT permission and warranty notice is retained in `LICENSE`.

`src/submission/static/brand/lucian.css` and `lucian.mjs` adapt interface
behaviors #032, #039, #070, #079 and #098. RubriQ maps colors to its theme,
creates DOM nodes without parsing HTML strings, and integrates the behaviors
with its document workflow. Their existing upstream attribution comments are
retained. The original adaptation revision was not recorded; checking the
current license does not establish a historical source digest.

The four `src/submission/static/brand/stat-*.svg` decorations were redrawn as
original primitive SVG geometry on 2026-11-16 for public distribution. They do
not contain the previous private Figma exports or downloaded Lucian graphics.
They retain the callers' view boxes and general palette. Those new drawings are
covered by RubriQ's Apache-2.0 license, not Lucian's MIT license.
