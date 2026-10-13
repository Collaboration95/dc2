# Linux integrated acceptance

CI run [38300284726](https://github.com/Collaboration95/dc2/actions/runs/38300284726)
passed all 15 checks for PR31 head `c0a7315c44ce89c03c8adb7b51ab39a1aca569d9`.
Actions checked out the synthetic merge `a9c14b925213fc5b3ff61d141be0bc74363144fc`.
This is full workflow evidence on that source, not a claim about subsequent changes.

The actual Firefox 155 workflow passed in **150.152 seconds** on a 4-CPU runner.
It exercised public replay/ownership/derived-copy/deletion, Publisher registration
and login, 30 accepted/completed files plus one rejection, authorised output access,
and stored-source retry after removing the local file. Browser actions included
registration, logout, login, upload, worker SIGKILL, failure visibility in **65.321s**,
one bodyless retry with no second upload, selected HLS playlists/segments and decoded
frames, separately decoded MP4, and owner deletion. Worker restoration passed.
The controlled invalid CLI source remains failed after retry, as expected; successful
recovery of a valid source is proved by the browser case.

Scoped browser TLS accepted the project CA and rejected an unrelated certificate
with `ignore_https_errors=False`. No system trust changes were made. Full routine
integration includes **47 Processing, 39 Media and 44 legacy** real tests, plus
one independent Publisher HTTPS test. The 47/39 cases include the previously
missing CT-20 source-invalid geometry and CT-21 deleted-derived-edit-key replay.
Fast checks passed **1,051 Python** and **152 frontend** tests. The complete browser
job took 5m18s including setup/builds; fast aggregate dependencies completed within
the three-minute CI target. No test was rerun to mask a failing assertion.

Combined statement/branch coverage: Processing **98.69%**, Media **98.19%**,
media engine **99.42%**, Publisher **98.43%**, inherited app **93.16%**.
Raw branches are 94.83%, 96.02%, 98.00%, 96.55% and 87.04%, respectively.
All distinct image scans and inherited checks passed. These are CI image scans;
V4 still separately scans its exact promoted local digest.

Selected original reports, screenshot and SHA-256 index are retained in
[`../evidence/linux-ci-38300284726/`](../evidence/linux-ci-38300284726/index.json).
Full CI log remains locally at `.cache/execution/ci-38300284726.log`; hosted
artifacts have a seven-day retention. Final macOS verification, full V2 faults,
V3 measurements and V4 good/bad release remain separate gates.
