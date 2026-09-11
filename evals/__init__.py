"""Headless scenario suite for RedTape — the eval number for the demo.

Each scenario stands up a fresh store + persona, drives one wake cycle with a
scripted trigger, and asserts on the *outcome state* (bookings, blocks,
decisions surfaced) rather than on the model's prose. Run:

    python -m evals.run            # all scenarios
    python -m evals.run quick      # the 3 demo-critical ones

Report is written to evals/reports/last-run.json and printed as a table.
"""
