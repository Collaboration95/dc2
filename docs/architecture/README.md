# Architecture documentation (V1 as built)

Source material for the report (sections 3.1 to 3.4) and slides 3 and 4. These pages describe what
the code and the rendered template do at this commit. They are not the report. The proposal's
AD-01 to AD-08, contract table and Figure 3 describe the earlier synchronous design; the
differences are tabulated, not hidden.

| Page | Issue | Contents |
|---|---|---|
| [ddd.md](ddd.md) | #187 | Ubiquitous language, two bounded contexts, aggregates and invariants, commands and events, context map, platform view, delta from Figure 3 |
| [decisions.md](decisions.md) | #188 | ADR register (AD-01 to AD-26 with status), proposal to as-built deviations, inconsistencies found, architectural limitations |
| [views.md](views.md) | #188 | Tiers and layers, nodes and subsystems, physical AWS view, persistence design, upload to play sequence |

Diagrams are Mermaid blocks inside the pages. `python3 docs/architecture/render_diagrams.py`
renders each block marked `%% img: <name>` to [`img/<name>.svg`](img/). The proposal's own images
under `project-documentation/images/` are untouched.

Evidence labels used in all three pages: **[AWS]** a live receipt
([`cloud-proof-r1017b.json`](../execution/aws/v1/evidence/cloud-proof-r1017b.json)), **[Local]**
tests on real PostgreSQL and FFmpeg with Moto for S3 and SQS, **[Code]** source or the rendered
template only, **[NOT_RUN]** implemented but never run on AWS.
