# Product Vision Document

### 1. Evolution of Voice Computing
Today, Kivi operates as a transactional transcription engine: *you speak, Kivi writes*. Semantic memory transforms Kivi into a persistent context layer—moving from capturing transient utterances to maintaining an evolving understanding of a user’s ongoing work.

While *Regular Dictation* remains strictly focused on converting speech to accurate written language using phonetic memory and styles, *Hey Kivi* becomes the context-aware interaction engine. It uses accumulated understanding across past interactions to execute tools, answer complex questions, and fulfill multi-step tasks without requiring manual context-setting.

```
Regular Dictation : "Capture what I say."
Hey Kivi          : "Use what I've previously said to help me now."
```

### 2. Selective Memory Taxonomy
Memory must be durable, grounded, and useful. Kivi employs a constrained taxonomy:

* **Facts:** Stable, explicitly established project parameters and structural details (e.g., *Project Atlas uses DuckDB*).
* **Preferences:** Explicit instructions on how the user prefers work executed (e.g., *Prefers concise reports*, *Prefers meetings before 5 PM*).
* **Episodes:** Key historical events, meeting outcomes, and time-bound interactions linked directly to source transcripts.

```
Transcript ──► Candidate Memory ──► Durable + Useful + Supported? ──┬─ YES ──► Store / Update
                                                                    └─ NO  ──► Ignore
```

#### What Kivi Deliberately Ignores
Selective forgetting is as vital as storage. Kivi deliberately ignores fillers, transient chit-chat, disposable daily updates, and implicit assumptions. A statement like *"I've been working late this week"* must **never** be stored as *"User prefers working at night."* Kivi may forget details; it must never invent them.

### 3. Handling Ambiguity & Evolutionary Memory
Memory is stateful and evolutionary, not purely additive. When a user’s context changes (e.g., switching a project database from PostgreSQL to DuckDB), Kivi resolves the change by marking past memories as **superseded** while activating the new state—preserving full lineage and reasoning.

```
[PostgreSQL] (status: superseded)  ──►  [DuckDB] (status: active | reason: local execution)
```

When signals are uncertain or incomplete, Kivi exposes that ambiguity directly:
* **Uncertain Signals:** Statements like *"I'm thinking of switching"* are staged as `uncertain` until explicitly confirmed.
* **Ambiguous Requests:** If a query spans multiple entities (*"What database am I using?"*), Kivi clarifies (*"Do you mean Atlas or Apollo?"*) rather than guessing.
* **Incomplete History:** If requested history is missing, Kivi explicitly refuses to guess (*"I know DuckDB is your choice, but history doesn't capture why"*).

### 4. User Control Surface & Provenance
Users are partners in memory accuracy, not system administrators. Kivi replaces complex vector logs with a clear **"Your Memory"** interface categorized by Decisions, Preferences, and Episodes. Users can edit or delete entries with a click.

Every memory surfaces an inline **"View Why"** trigger showing exact provenance:

$$\text{Answer} \implies \text{Active Memory} \implies \text{Source Transcripts + Lineage}$$

```
DuckDB (Current Decision)
  └── Why: "You explicitly stated you switched for local execution."
  └── Evidence: Transcript #102 (May 17) ──► Transcript #187 (May 22)
```

By keeping evidence fully traceable, Kivi establishes complete transparency—ensuring users trust the assistant enough to rely on it across their daily workflow.
