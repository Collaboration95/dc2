# Bounded cold recovery diagnostic correction

Good release `ec999b4f5326443980294aed3e71765d` promoted in96.887s and drained
real active work in31.873s. The following bad candidate did start and exit42 with
the expected marker. Its automatic rollback restored the good recovery container,
then the first owning-database diagnostic exceeded its15-second subprocess cap.
The freshly started recovery process and diagnostic interpreter share the recovery
container's hard1/16-CPU quota. The experiment remains FAIL and the pending intent
was retained; no false rollback-success claim was made.

The explicit `make rollback RUN_ID=final-local` recovery completed successfully
with the existing runner once that container was warm. It restored the exact tested
good image, passed public smoke, preserved Media and cleared pending intent. This
manual recovery does not turn the failed automatic experiment into PASS.

Increase only the diagnostic subprocess cold-start allowance from15to45seconds.
It is still clipped by the same absolute operation deadline. The300-second
rollback/drain and600-second promotion bounds,5-second DB connect/query timeouts,
exact-image proof and active-work assertions remain unchanged. There is no retry
loop or deadline reset. A controlled20-second cold diagnostic now succeeds with
adequate budget, while a10-second remaining budget still times out in10seconds.
109 offline release tests pass. A new complete good/bad experiment is required.
