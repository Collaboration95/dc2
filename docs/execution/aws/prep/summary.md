> Historical AWS2 preparation summary; issue statuses below are the earlier scoped snapshot. See [V1/V2 handoff](../v1/README.md) for current phase/relationships and decision #46 / deferred #68.

# AWS preparation delivery

The user authorized preparation, local verification, integration and issue reconciliation. Actual AWS deployment and account operations were excluded. The delivery branch is `work/aws2-prep-20261015` at integration code head `c82fe99`. Main umbrella [PR70](https://github.com/Collaboration95/dc2/pull/70) remains a draft and is not merged.

Three implementation agents covered bundles of 9, 5 and 7 issues, an average of 7 per agent. The work keeps the two owned business services, the existing engine, the frontend and Publisher. It adds:

- native task credentials and signing
- inert infrastructure definitions
- finite workers and a single operator journal
- independent owner release and restoration
- private common exports
- client and evidence protocols

## Review and merge

Rounds 1–4 of the independent review returned REVISE, and every finding was corrected. Round 5 passed local preparation at `57f7c5f` ([audits](audits/)). PRs #75, #74, #73, #72 and #71 merged in that order, each at its exact head after every required hosted check passed. Two failed jobs were rerun, and nothing else:

- #75: a cold Docker-info call timed out before any test started.
- #73: one Media startup job was cancelled.

Both reruns passed on attempt 2. The integration tree is identical to the reviewed source. Receipts are in [completion.json](completion.json).

## Verification

The normal suite passed 1,418 Python and 152 frontend tests at `53f9dca`. The 283 focused preparation tests at `57f7c5f` overlap that suite and are not added to it. Required Ruff, CloudFormation schema and renderer checks passed. The generated peer probes passed both real authentication-dependency contracts over in-memory ASGI.

One coherent local run, R11, completed eight phases on clean source `53f9dca`:

1. finite worker drain
2. Processing promotion
3. Processing failed-candidate restoration
4. Media promotion
5. Media failed-candidate restoration
6. close
7. private export
8. wake

Four one-second fixtures of 1,881 bytes each were uploaded. The common private export was 44,877 bytes. `57f7c5f` only splits one generated assertion into equivalent lines. The final review accepted that change without relabeling R11's source.

R11 ran against actual local containers. It exercised SQL/RQ, migrations, role probes, private HTTP probes, encoding, range requests, downloads, decoding, deletion and private dumps. Its AWS inventory and registry/scan inputs were synthetic. The two modes are reported separately. No backup or restore result is claimed.

An authenticated hosted ZAP scan executed and retained 12 alert types, all with risk code 0 or 1. Findings are report-only; execution errors fail the job.

## Issue outcomes

The current status policy keeps required AWS/account acceptance open until its assigned authentic evidence exists:

- **Closed for preparation:** sixteen issues #47–#62. Their verification contracts assign live evidence to the designated cloud acceptance issues; local mocks and emulation do not satisfy those live criteria.
- **Open and Blocked:** account/origin prerequisites #45/#46 and authentic acceptance #63–#67, plus all four epics #41–#44 (eleven items). Each has a concrete blocker note. Workflow is Blocked and built-in Status is Todo.
- **Closed as not planned:** optional automation #68, which is not a required acceptance dependency.

No issue is Ready in the current no-AWS scope. [Fresh status reconciliation](evidence/status-reconciliation.json) supersedes the retained historical all-closed snapshots. Original issue contracts and acceptance boxes are unchanged. Local preparation and its review remain complete; authentic AWS/account acceptance does not.

## Preservation

- All 11 existing project and desktop containers kept their IDs, start times and images.
- All 30 historical closed/Done items and the #38/#39 rejections are unchanged.
- Original course documents, frozen evidence (final measurements at `f46599f`) and roadmap illustrations are preserved.
- The test namespace `aws2-prep-r1` stopped without deleting its volumes.
- Inherited Alibaba was not operated.

## Not done

Account, budget and origin decisions and authentic cloud acceptance remain open and Blocked. Optional automation remains excluded. None of the following is certified: IAM, Fargate, CloudFront, quotas, memory pressure or state continuity, timed cloud latency, bills, resource deletion or restore. The existing forecast and the Singapore calendar anchor are unchanged.
