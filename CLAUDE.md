# CLAUDE.md — Archon Documentation Contract

You are working in a repository that participates in the **Archon** RAG knowledge base.

Your primary responsibility in this repo:

> Keep `.kiro/docs` accurate, structured, and grounded in the actual code and infrastructure, so Archon can answer questions about this system reliably.

This file defines how you should behave when editing code or documentation in this repository.

---

## 1. Repository Scope

The human owner should fill this section out once.

- **Service name:** `ArchonAgent`
- **High-level purpose:**  
  `Archon agent implementation with Python modules for monitoring GitHub repositories, ingesting documentation, and providing RAG-based query capabilities.`
- **Type:** `service`
- **Primary runtime:** `Python containerized service`

When documenting, focus on this service's role in the overall system rather than generic technology explanations.

---

## 2. Archon Documentation Layout

All documentation that Archon ingests for this repo MUST live under `.kiro/docs/`.

By default, use these files and purposes:

1. `.kiro/docs/overview.md`  
   - High-level summary of what this service does.
   - Its responsibilities and place in the larger architecture.

2. `.kiro/docs/architecture.md`  
   - Main components.
   - Data flows.
   - AWS and external dependencies (Lambda, API Gateway, EventBridge, DynamoDB, OpenSearch, Bedrock, queues, etc.).
   - Diagrams in Mermaid are allowed but keep explanatory text nearby.

3. `.kiro/docs/operations.md`  
   - How to deploy and roll back.
   - How to debug common issues.
   - Important metrics, logs, and alarms.
   - Any runbook-style procedures for oncall.

4. `.kiro/docs/api.md`  
   - External interfaces:
     - REST/gRPC endpoints.
     - Event payloads.
     - Queues and topics.
   - High-level request/response shapes.
   - Do not duplicate full OpenAPI specs by default; link to them if they exist elsewhere.

5. `.kiro/docs/data-models.md`  
   - Core domain entities.
   - Data schemas.
   - How they map to storage systems (DynamoDB tables, OpenSearch indices, S3 buckets, etc.).

6. `.kiro/docs/faq.md`  
   - Common questions engineers ask about this service.
   - Concise, grounded answers.

If a file is missing but relevant, you may create it following these purposes.

---

## 3. Grounding and Provenance

All non-trivial statements in `.kiro/docs` must be grounded in this repository or clearly labeled as TODO.

**Acceptable sources:**

- Code in this repository.
- Infrastructure definitions in this repository.
- Existing `.kiro/docs/*` files.
- Explicit specs under `.kiro/specs/` if present.

**Unacceptable sources (for asserting facts):**

- Your own guesses or prior knowledge that cannot be confirmed from this repo.
- Generic knowledge of AWS or frameworks, unless used only as context.

Whenever you describe behavior, include a "Source" subsection if it is not trivial.

Example:

- Section text describing the ingestion Lambda, its triggers, and its outputs.

Then:

**Source**
- `src/document_monitor.py`
- `infra/archon-cron-stack.ts`

If you cannot find evidence for something:

- Do NOT state it as fact.
- Optionally add a "Gaps and open questions" section with TODOs, e.g.:

  - `TODO: Confirm whether this Lambda still supports the legacy path. No references found in current code.`

---

## 4. RAG-Friendly Writing Principles

Archon uses these docs as chunks in a RAG pipeline. Write to support retrieval and accuracy.

1. **Short, focused sections**

   - Use headings (`##`, `###`) to separate topics.
   - Avoid multi-page sections without breaks.
   - Each section should be coherent enough to stand alone as a retrieved chunk.

2. **Direct, factual tone**

   - Prefer:
     - "The query Lambda generates an embedding with Bedrock and performs a vector search in OpenSearch."
   - Over:
     - "Our blazing-fast AI service cleverly leverages cutting-edge technology."

3. **Explicit structure**

   - For flows (e.g., ingestion, query), use numbered lists or bullet lists.
   - For configuration, use tables or bullet lists with keys and descriptions.
   - For runbooks, use stepwise instructions.

4. **Avoid noise**

   - Do not include large, generic tutorials.
   - Do not paste external docs verbatim.
   - Summarize how external systems are used by this repo and, if needed, link out in a "Further reading" subsection.

---

## 5. Behavior When Coding vs Documenting

### 5.1 When Implementing or Refactoring Code

If you make a change that affects how the system behaves, you should also update `.kiro/docs`.

1. Identify which docs are affected:
   - New or changed Lambda?
     - At least `.kiro/docs/architecture.md` and `.kiro/docs/operations.md`.
   - New endpoint?
     - `.kiro/docs/api.md` (and possibly `overview.md`).
   - Schema changes?
     - `.kiro/docs/data-models.md`.

2. Update the corresponding docs in the same change:
   - Adjust descriptions to match the new behavior.
   - Add or update "Source" references.
   - Remove or fix stale references.

3. If you are unsure about a behavior:
   - Do not manufacture details.
   - Add a TODO with what needs clarification.

### 5.2 When Answering Questions About This System

When a user asks, for example:

- "How does the Archon ingestion flow work here?"
- "Which Lambda processes the `/query` API?"
- "Where is the vector index defined?"

You should:

1. Check `.kiro/docs` first:
   - If the docs are missing or wrong, correct them.
2. Then answer the question by referencing those docs.
   - Example: "See `.kiro/docs/architecture.md#document-ingestion-flow` for the full sequence."

This keeps the docs and the RAG knowledge base aligned.

---

## 6. What Not To Do

- Do not store secrets, tokens, or private credentials anywhere in `.kiro/` or in this `CLAUDE.md`.
- Do not describe internal security-sensitive details unless explicitly allowed by the repo owner.
- Do not use `.kiro/docs` as a scratchpad or brainstorming area.
  - Use it only for information that should be a stable source of truth.
- Do not contradict this file unless the repo owner updates it.

---

## 7. Archon Integration Notes (Customizable)

The repo owner can add per-repo specifics here.

Example:

- Archon ingests all `.md` files under `.kiro/docs/`.
- Certain internal runbooks should **not** be ingested by Archon and should live elsewhere.
- Any non-standard ingestion paths should be described.

Template:

- **Archon ingestion paths:**  
  `<Describe which paths Archon reads (e.g., .kiro/docs only).>`

- **Docs that should not be ingested:**  
  `<Describe any docs that must remain internal and out of Archon.>`

- **Special instructions for this repo:**  
  `<Any repo-specific quirks or overrides.>`

---

By following this contract, you ensure that:

- Engineers and agents get accurate, inspectable answers.
- Archon's RAG index reflects the real system architecture and behavior.
- Documentation remains maintainable and tightly coupled to the codebase.
