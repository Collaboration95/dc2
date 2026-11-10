### DP-3 Trusted owner identity and reusable public contract (Nguyễn Kim Long)

#### The problem

Nguyễn Kim Long is responsible for this problem's analysis and design. Browser and Publisher requests must share an owner decision across separately packaged services. A service credential authenticates a forwarding service but cannot establish the provenance of a caller-controlled `X-Owner-Id`. Distributing the JWT signing secret also lets every verifier mint sessions and couples each service to account rules.

Figures {@fig:dp3-problem-class} and {@fig:dp3-problem-sequence} model the forwarded-header candidate and its failure if the forwarder copies an unverified identity. They describe a rejected design, not the current runtime. The forces are owner isolation, current account decisions, independent service releases and a public interface usable without domain imports.

![Figure {#fig:dp3-problem-class}. DP-3 rejected service-secret/forwarded-identity structure.](figures/dp3-problem-class.png){width=15cm}

![Figure {#fig:dp3-problem-sequence}. DP-3 failure when a trusted forwarder copies untrusted owner identity.](figures/dp3-problem-sequence.png){width=15cm}

#### Candidate patterns

| Candidate | Benefit | Trade-off |
|---|---|---|
| Forwarded identity header plus shared service secret | Simple private HTTP integration | Requires the forwarder to derive identity correctly; a shared secret alone cannot validate a copied owner claim. |
| Shared JWT secret, verified by every service | Each service verifies sessions locally | Distributes signing authority; current user/role checks duplicate account access or need another dependency. |
| Gateway Lambda REQUEST authorizer, trusted Actor and per-service owner filtering | Centralizes session validation while each service enforces resource ownership | Adds a synchronous Media identity dependency and requires restricted backend invocation. **Chosen.** |

#### Why the chosen pattern

The chosen boundary combines an authorization gateway, an event-to-application adapter and a small shared contract. Media retains session/account authority. API Gateway invokes the **Media-owned Lambda REQUEST authorizer**, then invokes the selected API separately with its trusted Actor context. Each API applies owner filtering to its own resources. This addresses the presentation feedback about the authorizer's location without introducing another business service (`media/authorizer.py`, `scripts/aws/v1/definitions.py`).

#### Solution class and sequence diagrams

Figure {@fig:dp3-solution-class} labels the implementation roles. Each API instantiates `GatewayAdapter`; the adapter strips public owner/role headers, reconstructs cookies from the Gateway event, validates `Actor` and injects request state. The integration marker is a schema fence. Lambda resource policies restricting invocation to the configured Gateway establish the trust boundary.

![Figure {#fig:dp3-solution-class}. DP-3 actual authorization, adapter and local enforcement roles.](figures/dp3-solution-class.png){width=15cm}

Figure {@fig:dp3-solution-sequence} shows the separate invocations. The authorizer verifies HS256 claims and current `User`, returning role `publisher` for current user/operator accounts. Media revalidates its cookie and current User and compares them to Actor. Processing accepts adapter-injected Actor and scopes queries to `owner_id` (`media/api/deps.py`, `processing/auth.py`, `processing/v1_api.py`).

![Figure {#fig:dp3-solution-sequence}. DP-3 Gateway attachment, current-user validation and service-local ownership checks.](figures/dp3-solution-sequence.png){width=15cm}

#### Implementation decisions and verification

`GatewayAuthorizer` uses payload v2, simple responses, Cookie identity source and cache TTL zero; its URI targets `MediaAuthorizerAlias`. Public health and Media register/login/logout routes bypass it. Processing's handler needs neither Media's JWT secret nor its User table, although protected Processing requests still depend synchronously on the Media authorizer.

The reusable contract comprises `contracts/` and the OpenAPI HTTP document (Figure {@fig:dp3-contract-class}). `contracts/v1.py` defines `Actor`, `Source` and `Envelope`; `contracts/gateway.py` provides the common adapter. Publisher and `frontend/app.js` consume the HTTP interface described by `docs/api/media.openapi.json`, including reservation/finalize, status and optional playback links. They do not import the Python contract package. `contracts/README.md` specifies additive changes and staged consumer-before-producer version upgrades; only version 1 is currently implemented.

![Figure {#fig:dp3-contract-class}. DP-3 shared wire types and independent consumers of the OpenAPI HTTP contract.](figures/dp3-contract-class.png){width=15cm}

`tests/media/test_lambda_boundary.py` checks current roles, removed users and repeated decisions. `tests/v1/test_contract_fixtures.py` checks Media revalidation, owner-scoped Processing access, wire shapes and negative contexts. `tests/v1/test_local_gateway.py` checks forged-header stripping and anonymous denial. Publisher's import-boundary, direct-upload and schema tests support independent consumption; `test_public_schema_conformance_and_explicit_ca` specifically validates the proposal contract in `project-roadmap/design/05-contracts/public.openapi.json`. These local tests substantiate the design without asserting a fresh hosted authorization result.
