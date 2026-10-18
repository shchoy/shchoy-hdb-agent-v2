---
name: implement
description: "Implement a piece of work based on a spec or set of tickets."
disable-model-invocation: true
---

Implement the work described by the user in the tickets.

If an external API key is required and its not available, ask the user to provide it in the environment, and use it in the implementation.

Use subagents if required to try keeping the context below 100,000 tokens.

Use /tdd where possible, at pre-agreed seams.

Run typechecking regularly, single test files regularly, and the full test suite once at the end.

Once done, use /code-review to review the work.