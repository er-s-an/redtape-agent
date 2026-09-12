# RedTape concept

RedTape is a background agent for people managing paperwork across borders. The prototype focuses on a synthetic family trip and passport renewal: the departure date creates validity, processing and appointment constraints that an expiry reminder alone does not express.

A Strands agent reads confirmed document records and versioned sandbox rules, computes deadlines backward, checks appointments and prepares reversible artifacts. When the available plan requires a processing-cost or sequencing choice, it creates one executable Decision Inbox item. Human approval is scoped to the actual displayed option; deterministic hooks enforce action binding before follow-through.

The current prototype includes a passport → driver-license/lawful-status dependency model, local PDF draft, calendar holds, same-session persistence and a hash-chained ledger. It does not integrate with a live consulate or DMV. The recorded genuine model case is described in recorded-demo.md. Real agency connectivity, production privacy/identity contracts, broader rule coverage and real-user validation remain future work.

For the Everyday Agents track, the relevant product behavior is useful background work with a human decision at the cost/permission boundary. This is positioning, not a claim of measured user impact or a judging outcome.
