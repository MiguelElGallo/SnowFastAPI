# Final code, documentation and DEV release review

Snowflake deployed the corrected implementation in an isolated DEV environment. The service reported `RUNNING`, serverless compute and the exact immutable package version recorded in the release receipt. All 83 tests passed with warehouse, DEV and hosted checks enabled.

## Independent review and corrections

Three reviewers examined the API, pagination, Python client, dependencies, deployment tooling, grants, workflows, operator guides and rendered documentation. The next pass cross-reviewed the corrections. It caught a promotion race and an interruption during reader changes that the first set of fixes would have left in place.

| Area | Correction | Evidence |
| --- | --- | --- |
| Deployment target | Verify the organization and account through both the CLI and connector before writes. Bind generated SQL to the account and disable CLI substitution for rendered identifiers. | Two independent parsers demonstrated the original mismatch offline. In DEV the guard rejected a mismatched target with `-20001`. A quoted identifier containing an ampersand survived execution. |
| Publication | Upload to an isolated stage, identify the single new immutable version, promote that exact version in SQL, and compare the service’s reported repository, package, version and upgrade state. Publish and deploy share a per-user, per-service lock. | The corrected publication promoted the new package at the existing service URL. The new receipt matched the serving source. The stage was removed. A previous prepared manifest was covered by regression tests. |
| Roles and grant retirement | Require distinct project roles. Run metadata reads and grant operations with secondary roles disabled. Keep the old reader’s existing DCM demo grants through a managed-role transition, then share and retire in order. Ordinary grants and restricted caller grants have separate retirement files. | An owner with stronger secondary privileges available was denied metadata access under its primary role. A real DCM rotation plan retained the existing reader’s grants. Success and failed-build tests covered receipt and cutover ordering. |
| Missing sources and roles | Retire grants by exact identifiers. Ambiguous inventory or insufficient visibility stops recovery. Only verified absence permits continuing after a missing-object error. | The generated retirement SQL completed in DEV for an absent table and an absent reader. The service owner and grant administrator exercised their respective retirement paths. |
| API, types and client | Publish the actual string-detail error schema, include retry metadata, distinguish cancellation and timeout, serve Swagger assets at the service origin, preserve interval precision and normalize MAP keys. Release Playwright responses and support resuming with `--cursor`. | Hosted OpenAPI and actual errors now agree. Real Chromium queried the hosted route from Swagger. Real Snowflake SQL preserved nine interval fractional digits, a signed year-month interval and numeric-key MAP values. The client resumed across fresh authenticated processes. |
| CI and smoke tests | Validate lockfile freshness. Require explicit DEV/hosted opt-in and discover the demo page limit from deployed OpenAPI. | The locked sync, runtime requirements comparison, Ruff, formatting, type checks and workflow lint passed. Flag values `0` and `false` skipped the selected live tests. |

The published operator manual covers split administrator duties, reader handoff and rollback. The [release guide](../site/how-to/releases.md) lists the commands. The [original implementation review](implementation.md) and [documentation plan and three passes](documentation.md) retain the earlier evidence.

## Redeployment and real HTTPS checks

| Check | Observed result |
| --- | --- |
| DCM and data | The combined command ran DCM plan and deploy. DCM reported zero definition changes and the repeatable seed inserted zero rows. A separate post-deployment plan also reported zero changes. |
| Package and resources | The immutable version in the release receipt matched Snowflake. Six packaged runtime and dependency files matched the checkout byte for byte. The generated catalog matched the success receipt. |
| Hosting and SQL | Serverless minimum instances 0 and idle timeout 3,600 seconds. The X-Small query warehouse has 60-second auto-suspend. The final inventory contained the same four restricted caller grants and two service grants as before the audit. |
| Gateway | Anonymous health and data requests received HTTP 302 to Snowflake sign-in. Authenticated health and OpenAPI returned 200. A malformed cursor returned 400, an unknown route 404 and an over-limit request 422 with a string `detail`. Data pages carried `private, no-store`. |
| Shipped client | A named Snowflake connection retrieved IDs 1–5 over HTTPS. Page lengths were 2, 2 and 1. Prices were decimal strings and the terminal cursor was null. The live suite also exercised fresh-session continuation and the deployed maximum. |
| Swagger | Real Chrome rendered the hosted UI under the gateway’s content security policy. Its **Try it out** request returned IDs 1 and 2. All seven recorded paths used the service origin and returned 200. |

### Two identities

The normal deployment login read the five-row demo. A second key-pair-authenticated Snowflake user had a dedicated default role and service access. The temporary private key stayed in memory. Each phase opened a fresh session.

| Temporary role | Direct SQL | Hosted health | Hosted demo |
| --- | --- | --- | --- |
| Before table SELECT | Denied, `2003 / 42S02` | 200 | 403 |
| With SELECT on the demo table | IDs 1–5 | 200 | 200, all five rows matched SQL across three pages |
| After revoking SELECT | Denied, `2003 / 42S02` | 200 | 403 |

Snowflake query history recorded three successful data queries and two denials under the temporary default role. A fresh administrator session verified that the temporary user, role and upload stage were absent after cleanup. These checks cover ordinary table privileges. The demo has no masking or row access policy. Each such policy needs a comparison with the expected values for its intended users.

## Documentation and privacy

The strict Zensical build checked 741 links, fragments and assets across 16 HTML pages. All 25 external references checked in the README and operating guides resolved. All 30 live files matched the GitHub Pages artifact byte for byte. A missing nested URL served the project’s 404. Desktop and mobile Chrome checks covered light and dark themes, keyboard navigation and search, with no console or HTTP errors. The primary action measured 7.21:1 contrast.

The privacy review checked source files, Git history, and the generated site for account identifiers and credentials. Deployment receipts and raw verification evidence are stored separately from the source.

## Client and test setup follow-up

Public review identified ambiguous input in the browser client's service URL and a missing dependency group in the README's offline test command. The client now validates the host and passes a canonical origin to the browser. The command installs the locked client and test dependencies. An independent reviewer checked both changes.

In a fresh Python environment, 86 offline tests passed. With all four Snowflake checks enabled, all 90 tests passed. The revised client read all five demo rows from the deployed API, resumed pagination in a new process, and checked the maximum page size advertised by OpenAPI.

## Scope of the release verdict

The serverless table workflow passed the implementation review and the DEV acceptance checks. Use one publisher at a time across CI runners and preserve the last successful catalog. The default demo uses a standard table. The earlier intermittent hosted-view 403 remains a qualification item for each view. [Hosted view observations](../verification.md#hosted-views)
