> **Historical record of the pre-AWS local delivery (12 to 14 October).** Current target: [`aws/architecture-plan.md`](aws/architecture-plan.md) and [`aws/v1/README.md`](aws/v1/README.md).

# Issue and PR delivery map

| Key | GitHub issue | Epic | Wave | Dependencies | Planned PR group |
| --- | --- | --- | --- | --- | --- |
| G1 | [#7](https://github.com/Collaboration95/dc2/issues/7) | E0 | 0 | none | Planning |
| G2 | [#8](https://github.com/Collaboration95/dc2/issues/8) | E0 | 0 | G1 | Planning |
| F1 | [#9](https://github.com/Collaboration95/dc2/issues/9) | E1 | 1 | G2 | Foundation |
| F2 | [#10](https://github.com/Collaboration95/dc2/issues/10) | E1 | 1 | G2 | Foundation |
| F3 | [#11](https://github.com/Collaboration95/dc2/issues/11) | E1 | 1 | F1, F2 | Foundation |
| P1 | [#12](https://github.com/Collaboration95/dc2/issues/12) | E2 | 2 | F3 | Processing |
| P2 | [#13](https://github.com/Collaboration95/dc2/issues/13) | E2 | 2 | P1 | Processing |
| P3 | [#14](https://github.com/Collaboration95/dc2/issues/14) | E2 | 2 | P2 | Processing |
| M1 | [#15](https://github.com/Collaboration95/dc2/issues/15) | E3 | 2 | F3 | Media |
| M2 | [#16](https://github.com/Collaboration95/dc2/issues/16) | E3 | 2 | M1 | Media |
| M3 | [#17](https://github.com/Collaboration95/dc2/issues/17) | E3 | 2 | M2 | Media |
| C1 | [#18](https://github.com/Collaboration95/dc2/issues/18) | E4 | 2 | F3 | Clients |
| C2 | [#19](https://github.com/Collaboration95/dc2/issues/19) | E4 | 2 | F3 | Clients |
| V1 | [#20](https://github.com/Collaboration95/dc2/issues/20) | E5 | 3 | P3, M3, C1, C2 | Integration |
| V2 | [#21](https://github.com/Collaboration95/dc2/issues/21) | E5 | 3 | V1 | Integration |
| V3 | [#22](https://github.com/Collaboration95/dc2/issues/22) | E5 | 4 | V1 | Evidence and handoff |
| V4 | [#23](https://github.com/Collaboration95/dc2/issues/23) | E5 | 4 | V1 | Evidence and handoff |
| V5 | [#24](https://github.com/Collaboration95/dc2/issues/24) | E5 | 4 | V2, V4 | Evidence and handoff |
