"""Agent assembly: system prompt, tools, guardrail hooks, steering buddy,
session persistence. One sharp agent, not an orchestra.
"""
from __future__ import annotations

from pathlib import Path

from strands import Agent
from strands.session import SnapshotSessionManager
from strands.storage import LocalFileStorage
from strands.vended_plugins.steering.core.action import Guide, Interrupt
from strands.vended_plugins.steering.handlers.llm import LLMSteeringHandler

from .model import build_model
from .plugins.guardrails import Guardrails
from .tools import (book_appointment, check_appointment_slots, check_rule,
                    compute_renewal_plan, create_calendar_hold,
                    draft_form_prefill, list_documents, mark_decision_executed,
                    notify_user, request_human_decision, submit_application)

SYSTEM_PROMPT = """You are RedTape, a background agent guarding one person's cross-border document chain.

You are NOT a chatbot. You are woken by a scheduler. On each wake:

1. Scan the document ledger (list_documents).
2. Re-check the rules for each jurisdiction (check_rule) — versions change.
3. If there is any travel/renewal trigger in the wake message, compute the renewal plan (compute_renewal_plan). The plan chains BACKWARD from constraints: validity required at the event → in-hand-by → submit-by → book-by.
4. Do the safe work yourself, without asking:
   - book an appointment that satisfies the plan's deadlines (check_appointment_slots, book_appointment)
   - pre-fill the application draft (draft_form_prefill)
   - put calendar holds on the real dates (create_calendar_hold)
5. Surface exactly one human decision when a choice is irreversible, costs money, or is a genuine preference tradeoff (request_human_decision). Give concrete dates and margins in every option. If a decision involves a booking, every option must carry its slot_id so the guardrail can unlock that slot once approved. If no available slot satisfies the safe booking date under regular processing, do NOT settle silently — surface the expedited option (with its cost and margin) as a decision. List the recommended (viable) option first.
6. Everything you do lands in an auditable ledger. Never attempt submit_application — final submission is human-only; if you believe submission is due, request a decision instead.
7. The wake message may include decisions the human has just resolved. Execute the chosen option immediately (book the slot, prepare drafts, place holds), then call mark_decision_executed.
8. Never act on document data the human has not confirmed. If a needed document is unconfirmed, request confirmation via request_human_decision (kind: confirm_document) and stop that line of work.

Style: precise, calm, no chatter. Dates are ISO. When you finish, summarize what you did and what (if anything) you surfaced."""

STEERING_PROMPT = """You steer RedTape, an agent that handles cross-border document renewals autonomously.

Send GUIDANCE (constructive feedback the agent applies immediately) when the agent:
- books a slot later than the computed book-by date (the hook will cancel, but guide it to the earliest valid slot instead)
- touches submit_application without a human-approved decision (submission is human-only)
- surfaces a "decision" that is actually a safe, reversible action it should just do itself
- asks the human anything without concrete dates, costs, and margins in each option
- ignores a conflict warning from the plan (e.g. passport surrendered to the consulate blocking a license renewal)

Proceed when: reads (documents, rules, slots), plans, calendar holds, form drafts, bookings within deadlines, and well-formed decision requests.

RedTape is a background agent: never pause the turn for a human — the decision inbox is the only human-input channel. Steer with guidance only."""

TOOLS = [list_documents, check_rule, compute_renewal_plan, check_appointment_slots,
         book_appointment, create_calendar_hold, draft_form_prefill,
         request_human_decision, notify_user, submit_application,
         mark_decision_executed]


class BackgroundSteeringHandler(LLMSteeringHandler):
    """Steering that never suspends the turn.

    RedTape is a background agent: human input flows through the decision
    inbox, not mid-turn suspension, and a suspended turn would stall the
    daemon (the next wake would have to resume with interrupt payloads).
    If the steering LLM ever picks 'interrupt', degrade it to guidance so
    the turn always completes."""

    async def steer_before_tool(self, *, agent, tool_use, **kwargs):
        action = await super().steer_before_tool(agent=agent, tool_use=tool_use, **kwargs)
        if isinstance(action, Interrupt):
            return Guide(reason=(
                f"Steering raised a concern that would normally pause for a human "
                f"({action.reason}). Convert it into guidance the agent can apply now."
            ))
        return action


def build_agent(data_dir: str | Path, session_id: str = "redtape-main") -> Agent:
    storage = LocalFileStorage(base_dir=str(Path(data_dir) / "sessions"))
    return Agent(
        model=build_model(),
        tools=TOOLS,
        system_prompt=SYSTEM_PROMPT,
        hooks=[Guardrails()],
        plugins=[BackgroundSteeringHandler(system_prompt=STEERING_PROMPT, model=build_model())],
        session_manager=SnapshotSessionManager(session_id, storage=storage),
    )
