# Performance wave — 13 October 2026

Baseline87389d1; deadline11:55 Asia/Singapore. [Epic#33](https://github.com/Collaboration95/dc2/issues/33) tracks three independent GPT6.1Sol xhigh implementation lanes, clean-context Sol reviews and coordinator acceptance. No cloud operations or spending. Future infrastructure must fit $200 total for approximately three weeks.

| Lane | Change and bounded evidence | Research |
| --- | --- | --- |
| [Media#34](https://github.com/Collaboration95/dc2/issues/34) | Release login read connection before bcrypt; checked-out connections1→0 at verification in a real one-slot SQLAlchemy pool | [Local record](media.md), [gist](https://gist.github.com/Collaboration95/f0fbf94bb1dac57acba26f74329b5c99) |
| [Processing#35](https://github.com/Collaboration95/dc2/issues/35) | Hash output while uploading; logical file bytes read2N→N, opens2→1, executor submissions2→1 using installed SDK reader/multipart loop | [Local record](processing.md), [gist](https://gist.github.com/Collaboration95/8530d1e5518bfb838617fe3d6fd972b5) |
| [Publisher#36](https://github.com/Collaboration95/dc2/issues/36) | Reuse bounded full-file hashing buffer; measured peak Python allocation2,102,230→267,553bytes for8MiB input, identical identity | [Local record](clients.md), [gist](https://gist.github.com/Collaboration95/f0a71ff3ccf52a5c9e5b9dae4cf24de6) |

These are operation-count/resource measurements, not end-to-end latency, RSS, cloud-cost or encoding speed claims. No authentication cost, ownership rule, output quality or interface was weakened. Historical full scaling/latency evidence remains attributed to its original source.

[Scope and acceptance record](https://gist.github.com/Collaboration95/613cc9dcaacde8e741250da6b6b5e4cb). [Independent architecture research](https://gist.github.com/Collaboration95/539bb05a65c9eb8663afd201f0e3d198) recommends retaining the consolidated topology and testing CPU quota redistribution and bounded worker scheduling before purchasing more infrastructure. These are unproven follow-up experiments; no runtime quotas were changed.

The linked epic/issues and PR retain the subsequent clean-context review gists, exact CI results, merge state and follow-up decisions. This source record precedes those gates and does not claim they already passed. Required CI must succeed before merge; work still pending at11:55 remains explicitly in Review. Existing local demo images were not rebuilt by this wave, so the running demo does not automatically contain these changes.
