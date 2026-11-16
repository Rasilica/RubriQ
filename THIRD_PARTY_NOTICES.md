# RubriQ third-party notices

Original RubriQ code is licensed under the Apache License, Version 2.0; see
[LICENSE](LICENSE). This grant and the project license metadata apply to original
RubriQ code. Third-party code, reference material, libraries, runtimes, fonts and
user documents retain their own licenses and rights. This file does not relicense
them or certify a distributable bundle.

## Included source and library material

### Lucian UX/UI Prompt — MIT

- Official site: [Lucian UX/UI Prompt](https://lucianlabs.dev/uxui-prompt/).
- Upstream: [Seokwoooo/lucian-uxui](https://github.com/Seokwoooo/lucian-uxui).
- Adapted material: `src/submission/static/brand/lucian.css` and `lucian.mjs`,
  behaviors #032, #039, #070, #079 and #098, modified for RubriQ's theme,
  DOM construction and workflow integration.
- Copyright (c) 2026 Seokwoooo.
- Full MIT permission and warranty notice: [vendor/lucian/LICENSE](vendor/lucian/LICENSE).
- Source and modification details: [vendor/lucian/PROVENANCE.md](vendor/lucian/PROVENANCE.md).

Retain the upstream attribution comments and full MIT notice with these
adaptations. The four `static/brand/stat-*.svg` decorations were replaced with
original primitive SVG drawings on 2026-11-16; the public source contains no
private Figma export files for those decorations. The replacement drawings are
original RubriQ material covered by Apache-2.0.

### im-not-ai — MIT

- Upstream: [epoko77-ai/im-not-ai](https://github.com/epoko77-ai/im-not-ai/tree/2f3d943d08056b612a92e12bfb72ea94dd2acd18).
- Included material: `vendor/im-not-ai/local_metrics.py` (selected function and
  constant excerpts) and `vendor/im-not-ai/quick-rules.md` (reference rules).
- Upstream copyright: Copyright (c) 2026 epoko77-ai.
- Full permission and warranty notice: [vendor/im-not-ai/LICENSE](vendor/im-not-ai/LICENSE).
- Scope and adaptation details: [vendor/im-not-ai/PROVENANCE.md](vendor/im-not-ai/PROVENANCE.md).

Retain the upstream copyright and full MIT permission notice when distributing
copies or substantial portions of this material, including adapted excerpts.

### hwplib 1.1.11 — Apache-2.0

- Upstream: [neolord0/hwplib](https://github.com/neolord0/hwplib).
- Included artifact: `vendor/hwplib/1.1.11/hwplib-1.1.11.jar`, used by the Java HWP
  structure worker and sample tooling.
- Full license: [vendor/hwplib/1.1.11/LICENSE](vendor/hwplib/1.1.11/LICENSE).
- Artifact source and recorded digest: [vendor/hwplib/1.1.11/PROVENANCE.md](vendor/hwplib/1.1.11/PROVENANCE.md).

Preserve its license and applicable upstream attribution notices. Include any
upstream NOTICE supplied with a redistributed version and mark modified upstream
files as required by Apache-2.0. RubriQ's license does not establish ownership of
hwplib.

## Separately provisioned conversion runtimes

Python keyring is an installed dependency for OS credential storage, licensed
under MIT. Its distribution includes its full license notice. See
[jaraco/keyring](https://github.com/jaraco/keyring); retain the dependency's
license and its dependencies' notices when distributing a bundled environment.

The public source export excludes Java runtimes, LibreOffice applications,
H2Orestart extension binaries, installed conversion profiles and local `.runtime/`
contents. Users provision these separately. License texts and provenance notes
may be retained without the corresponding runtime binary. Copying runtime
directories into a later archive, installer or container would redistribute
their contents; the original-code Apache grant is insufficient for that distribution.

### H2Orestart 0.7.14 — GNU GPL version 3

- Upstream source: [H2Orestart v0.7.14](https://github.com/ebandal/H2Orestart/tree/v0.7.14).
- Optional extension: H2Orestart.oxt, installed by the user into a dedicated
  LibreOffice profile for HWP/HWPX conversion; not included in the public source export.
- Full license: [vendor/h2orestart/0.7.14/COPYING](vendor/h2orestart/0.7.14/COPYING).
- Local artifact provenance: [vendor/h2orestart/0.7.14/PROVENANCE.md](vendor/h2orestart/0.7.14/PROVENANCE.md).

H2Orestart remains GPL-licensed. Any distribution that includes its extension,
JAR or installed profile copies must satisfy the applicable GPL conditions,
including the required license notices and Corresponding Source arrangements.
An upstream source link in this file alone does not certify compliance. Review
the actual packaging and integration before distributing it with RubriQ.

### LibreOffice — MPL-2.0 and component-specific licenses

RubriQ invokes a separately installed LibreOffice application for conversion.
LibreOffice identifies its license as MPL-2.0 and includes components under other
licenses; see the [official license page](https://www.libreoffice.org/licenses/)
and the LICENSE file supplied with the exact installed version. Preserve those
terms and meet the applicable source-availability requirements if distributing
LibreOffice or modifications. Its application and bundled components are not
covered by RubriQ's Apache grant.

### Java runtimes

Java runtimes are separately installed and are not included in the public source
export. The exact JDK's legal tree contains its license, exceptions and
component-specific notices. Preserve those notices and evaluate that runtime's
redistribution and source requirements before including it in a future binary
release. A Java runtime is not relicensed under RubriQ's Apache license.

## Fonts, documents and other dependencies

The web interface uses a local system font stack. Naming a system font does not
grant redistribution rights to its font files. Conversion may use fonts installed
on the host or supplied with LibreOffice; each font's own license governs copying,
embedding and redistribution. A generated font manifest records observations and
does not grant a font license.

User-supplied documents and their embedded material retain their owners' rights.
Python and development dependencies declared in `pyproject.toml` and resolved in
`uv.lock` also retain their respective licenses. This notice is not a complete
inventory of every transitive package or a clearance for a future binary release.
For each release, inspect the actual contents and retain all applicable license,
copyright and attribution notices and required source materials.
