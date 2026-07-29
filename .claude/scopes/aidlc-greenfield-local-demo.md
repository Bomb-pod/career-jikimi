---
name: greenfield-local-demo
depth: Standard
keywords: []
description: Greenfield local demo — design-doc-led, no operations, no CI
skeleton: on
---

# greenfield-local-demo scope

Standard depth for a greenfield build that ships to a laptop, not to
production, and whose architecture has already been settled in a design
document before the workflow starts. Composed by the adaptive composer at
ARS 44 (Standard band) from a flat-MED entropy profile with no HIGH
component.

Fourteen of 32 stages. It keeps the full design-and-build spine — practices,
requirements, application design, units, delivery planning, functional
design, code, tests — and cuts three things: brownfield discovery (there is
no prior code), the operations phase (there is no deployment target), and
the framing stages whose output the design document already contains.

## When this scope fits

All four must hold, or reach for `mvp` instead:

- **Greenfield in the strict sense** — zero application code in the
  workspace, so `reverse-engineering` has nothing to read.
- **A design document already exists** and resolves the stack, the data
  model, and the load-bearing contracts. This is what makes `feasibility`
  and the second mockup pass foldable; without it they are not.
- **No deployment target** — no cloud, no environments, no on-call. The
  runtime is a local process plus a docker-compose dependency.
- **No CI service or PR flow**, so a pipeline definition would never fire.

Test strategy stays Standard despite the demo framing. That is deliberate:
these projects are usually instruments for measuring something, and a
measurement instrument with weak tests measures its own bugs.

## Why these stages, why skip those

**Ideation (3 of 7).** `intent-capture` and `scope-definition` are cost-1
stages that earn their place against Unresolved Assumptions — a design
document that is complete on architecture is usually still carrying an
explicit open-questions list and a set of provisional decisions, and those
are the cheapest entropy in the whole grid to retire. `rough-mockups`
carries the UX narrative alone. `market-research` goes because a demo built
to test a hypothesis has no market to research; `team-formation` because
the team is one person; `approval-handoff` because there is no second team
to hand off to and the per-stage gates already put a human in the loop
everywhere.

**Inception (5 of 8).** `reverse-engineering` is the defining skip: on a
truly empty workspace it would produce an empty map, and downstream stages
run on requirements instead. That skip is what forces `practices-discovery`
to EXECUTE — the fold that normally absorbs it (conventions embodied in
existing code) has nothing to absorb it into, and a greenfield repo has no
linter, no formatter, no test framework, and often no git repo yet.
`requirements-analysis` stays because a design document is prose, not a
spec: converting stateful contracts into pass/fail criteria is real work
that three downstream stages consume. `user-stories` folds into it whenever
the persona count is one. `refined-mockups` folds into `rough-mockups` when
the design document has already fixed the non-obvious UI states — one design
pass, placed early where it can still inform architecture, beats two.

**Construction (3 of 7).** `functional-design` earns a cost-4 slot wherever
the logic is a genuine state machine rather than CRUD. The NFR pair folds:
`nfr-requirements` into `requirements-analysis` when the design document has
already quantified the one or two NFRs with teeth, and `nfr-design` after it,
since with no separate NFR spec there is nothing left to design against.
`infrastructure-design` is negative expected value when the only
infrastructure is a docker-compose file whose constraints are already
written down. `ci-pipeline` goes with the missing repo and remote.

**Operation (0 of 7).** Nothing is deployed, monitored, or on-call, so all
seven skip wholesale. Note that a product-level metrics or audit table is
not an argument for `observability-setup` — that is a data model owned by
functional design, not an ops telemetry stack.

## Fold triggers — when to un-skip

Each fold below is a default, not a law. The named trigger flips it back:

| Folded stage | Absorbed by | Un-skip when |
|---|---|---|
| `feasibility` | `application-design` | the approach is genuinely novel, or risk is high enough that viability must be proven before design |
| `refined-mockups` | `rough-mockups` | the demo acquires an audience beyond its author |
| `user-stories` | `requirements-analysis` | more than one persona, with conflicting journeys |
| `nfr-requirements` | `requirements-analysis` | a measurement or benchmarking track enters *this* workflow rather than a later intent |
| `nfr-design` | `functional-design` | `nfr-requirements` is un-skipped, or NFRs start interacting |
| `infrastructure-design` | `code-generation` | any real deployment target appears |
| `ci-pipeline` | `build-and-test` | a repo and remote exist and a coverage floor should be mechanically enforced |
| `reverse-engineering` | — (nothing to read) | any prior application code exists — then this scope is the wrong one |
| `performance-validation` | — (later intent) | the measurement track starts |

## Walking skeleton

`skeleton: on`. These builds tend to stack a realtime transport, a database
with a non-trivial ordering or locking contract, and a third-party API into
one request path, and the integration risk concentrates exactly where those
three meet. Bolt 1 runs a gated end-to-end vertical slice through all of
them before the remaining Bolts start. That slice cuts *across* the units
rather than along them, which is why `delivery-planning` stays EXECUTE here
even at a low unit count — `units-generation` decomposes by capability and
does not produce it.

## Membership

No keyword triggers — `keywords: []`. This scope is composed, not inferred:
resolve it explicitly with `/aidlc --scope greenfield-local-demo`. Making it
inferable is a separate human decision, and would need a collision check
against the stock scopes first.
