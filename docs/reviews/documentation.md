# Documentation plan and reviews

## Draft plan

**Audience.** An API consumer has a Snowflake identity and an administrator-supplied service URL. A dataset publisher or deployment operator also has the implementation checkout and a named Snowflake connection. GitHub Pages can serve the manual independently of the application. Give both audiences a starting point they can actually use.

| Reader need | Pages and success condition |
| --- | --- |
| Learn by doing | Read the five-row demo through a signed-in browser. The reader requests two rows, uses the returned cursor, and recognizes the terminal page. |
| Complete a task | Provision and deploy DEV, publish a table with TOML, use the Python client, share or retire access, test changes, and recover a release. Each guide names the responsible role and gives a result the reader can check. |
| Look up a fact | Document configuration keys, identifier rules, projection and key types, response fields and status codes, client flags, operator commands, release files and runtime limits. Check names and defaults against the exact local release. |
| Understand a choice | Explain how Snowflake authenticates each request, who authorizes SQL, why DCM and the application deploy separately, how keyset pagination behaves when data changes, and how idle compute is billed. |

**Presentation.** Use the modern Zensical theme, a high-contrast navy and teal palette in light and dark modes, a visible table of contents, keyboard search, and mobile navigation. Teach through one consistent demo. Use an architecture figure with an accompanying text description if it improves the explanation.

**Publication.** Publish the manual with GitHub Actions Pages and verify the live project subpath. Use sample values in examples. Keep account identifiers, credentials, deployment receipts and raw test evidence in private storage.

**Review sequence.** Independently review this plan, revise it, draft the site, then run three separate peer passes on the actual manual. Review reader tasks and language first, commands and contract accuracy second, and rendered navigation, accessibility and publication third. Repair each material finding and check the affected pages. Use a strict build, check links and fragments, exercise examples against the locked implementation, and test the published site on desktop and mobile.

The plan uses the four reader needs in [Diátaxis](https://diataxis.fr/) and the step-by-step language of the [FastAPI tutorial](https://fastapi.tiangolo.com/tutorial/first-steps/).

## Plan review and revision

An independent reviewer approved authoring with four changes. The home page will give consumers a browser-only route and identify the implementation checkout prerequisite for operators. The tutorial will show the actual final cursor. Troubleshooting will distinguish gateway sign-in, data privileges, input errors and hosted views. The release check will inspect the public ref's ancestry and files, the generated artifact, and the live site under its project path. Each post-draft pass will identify the reviewed revision, corrections and retest. Pass three will measure contrast and exercise keyboard and mobile navigation.

## Pass 1. Reader tasks and language

The independent reviewer read the 15-page draft and scored it 8.5/10. The revised draft separates SQL inspection from execution, makes the plan a real checkpoint, defines the publisher's shell variables, shows how a reader receives the demo role and explains how to replace an existing URL path. It also moves rollback SQL next to its step and gives support information that a browser reader can actually provide. The strict build passed and the rendered-link check found 752 valid links and assets.

## Pass 2. Technical accuracy

A second reviewer compared all 15 pages with the implemented release, giving the draft 90/100. Revisions distinguish manual package and route checks from the combined deployer's readiness check, document the two grant administrators' authorities, and specify the order for removing a published source. They define the direct-query baseline for a two-user test and correct the behavior of regular columns, fractional VARIANT numbers and MAP strings. We validated CLI help for six operator commands and the client, four TOML examples, final-page JSON, the OpenAPI limit and the data-type examples.

## Pass 3. Rendered site, accessibility and publication

The reviewer opened all 15 content pages at viewport widths of 390 and 1,440 CSS pixels. They found one mobile keyboard defect and scored that draft 8.5/10. Navigation links could receive focus while their drawer was closed. In the revised theme, the closed drawer is inert, the menu and search triggers are named, and closing the menu restores focus. The reviewer retested Enter, Space, Escape, search results, resize and keyboard-only navigation to the tutorial. The final score for this pass was 9.8/10.

The rendered three-step request flow remains readable on mobile. The primary button measured 7.21:1 contrast in both themes. The revised home page made zero external requests during browser checks. The strict build and checker verified 768 same-site links, fragments and assets across 16 HTML files, including the error page. All 16 distinct external reference URLs in the first technical check resolved; the subsequent Snowflake caller-grant anchor was also checked. The public commits were inspected for documentation-only ancestry and file contents before publication.

## Publication read-back

The first documentation Pages workflow built and deployed successfully. All 15 content routes returned HTTP 200 and a missing nested route returned the site's styled 404. The public homepage, search index and custom CSS and JavaScript matched the uploaded artifact byte for byte. The 30-file artifact contained the expected generated files. Live Chrome checks passed in light and dark themes and on mobile, including keyboard search, drawer focus restoration and the flow graphic. The combined application checkout again passed all 38 tests.

GitHub's automated review identified a race between consecutive default-branch builds. The corrected workflow serializes builds and deploys per ref and checks the current remote revision before uploading. Actionlint passed. An isolated Git test published the current revision and skipped a stale revision. The PR check built the site and skipped deployment. The final Pages run built and deployed the default branch. All 15 live HTML pages, the search index, custom CSS and JavaScript matched this deployment artifact byte for byte.
