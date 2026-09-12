# Judge testing instructions

1. Use a fresh clone, Python 3.13, the requirements-lock.txt dependencies and the editable project install described in README.
2. For a real model run, provide your own KIMI_CODE_API_KEY in the shell. Never enter it in the app or commit it. Run bash scripts/demo.sh and open localhost:9200.
3. The synthetic Xiao seed uses a November 20 trip and April 15, 2027 passport expiry. Press Run agent check. Allow several minutes for primary-model and steering calls.
4. Inspect the activity drawer: documents/rules/plan/availability, reviewable draft, local holds and the late-slot permission boundary. Model wording can vary; the dated rules and hard permission checks are deterministic.
5. When a concrete expedited option is surfaced, review its actual fee, projected return and exact slot. Approve the intended displayed option. The app wakes the agent for follow-through; look for the matching sandbox confirmation and verified local hash chain.
6. No government application should be filed for the booking-only path. The demo portal, records and receipts are synthetic.

Without a model credential, inspect docs/demo-proof.json and run the deterministic Python tests against a separate local mockgov process. The tests themselves do not invoke the model. Node is needed only for the optional UI display regression test, not to run the Python app.

A source-level diagnostic follow-through can use the daemon wake path after an inbox decision is resolved. Do not manually call a tool and label it model-selected. Do not silently substitute a deterministic replay for a failed hosted run.
