# GPT-6.1 Sol Notes

Recommended root for this skill: `gpt-6.1-sol`.

Suggested starting profile for everyday orchestration:

- reasoning effort: `high`
- Standard speed

Choose a reasoning effort/speed available in your installed Codex client.
Supported options and availability can change; this document is not a model
capability catalog. Installation never selects a model or starts a paid request.
GPT-5.6 Sol users can keep their existing root and single-worker setup.

The orchestration objective is to keep Sol focused on high-value root work:

- requirements interpretation;
- architecture and contracts;
- deciding whether work is parallelizable;
- producing clean worker contracts;
- acceptance and risk judgement;
- durable project-state updates.

Avoid using higher reasoning simply because it is available. Increase to `xhigh`/`max` only for hard architecture/debugging/review cases where the quality gain justifies extra model work.

The model has a large context window, but the workflow intentionally externalizes durable state into the repository. A large window should not become a reason to keep obsolete debugging history forever.
