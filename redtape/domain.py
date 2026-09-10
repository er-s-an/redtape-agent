"""The dependency-graph core: renewal deadlines computed backwards from constraints.

A reminder app walks forwards from an expiry date. RedTape walks backwards
from the moment a document must be *in hand and valid*, through processing
time and appointment lead time, to the latest safe filing date — and flags
conflicts where one renewal blocks another (e.g. the consulate keeps your
passport while your license renewal needs it).
"""
from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date

from dateutil.relativedelta import relativedelta


@dataclass
class Document:
    doc_type: str
    jurisdiction: str
    expiry: date
    number: str = ""
    holder_name: str = ""


@dataclass
class RenewalRule:
    jurisdiction: str
    doc_type: str
    processing_weeks_max: int = 0
    appointment_lead_days: int = 7
    requires_appointment: bool = True
    surrenders_current: bool = False
    renewal_window_days_before_expiry: int | None = None


@dataclass
class TravelEvent:
    date: date
    description: str
    min_passport_valid_months: int = 6


@dataclass
class PlanStep:
    doc_type: str
    action: str
    latest_date: date
    reasons: list[str] = field(default_factory=list)


@dataclass
class Plan:
    steps: list[PlanStep]
    conflicts: list[str]

    @property
    def needs_action(self) -> bool:
        return bool(self.steps)


def plan_for_travel(event: TravelEvent, passport: Document,
                    passport_rule: RenewalRule, today: date,
                    safety_buffer_days: int = 7) -> Plan:
    valid_needed_until = event.date + relativedelta(months=event.min_passport_valid_months)
    if passport.expiry >= valid_needed_until:
        return Plan(steps=[], conflicts=[])

    in_hand_by = event.date - relativedelta(days=safety_buffer_days)
    submit_by = in_hand_by - relativedelta(weeks=passport_rule.processing_weeks_max)
    reasons = [
        f"{event.description} on {event.date.isoformat()} requires passport valid "
        f"{event.min_passport_valid_months} months beyond stay (until {valid_needed_until.isoformat()})",
        f"current passport expires {passport.expiry.isoformat()} — insufficient",
        f"new passport in hand by {in_hand_by.isoformat()} (buffer {safety_buffer_days}d)",
        f"consulate processing up to {passport_rule.processing_weeks_max} weeks",
    ]
    steps = [PlanStep(
        doc_type="passport",
        action="renew",
        latest_date=submit_by,
        reasons=reasons,
    )]
    if passport_rule.requires_appointment:
        appt_by = submit_by - relativedelta(days=passport_rule.appointment_lead_days)
        steps.append(PlanStep(
            doc_type="passport",
            action="book_appointment",
            latest_date=appt_by,
            reasons=[f"appointment needed before submission, lead {passport_rule.appointment_lead_days}d"],
        ))
    return Plan(steps=steps, conflicts=[])


def plan_license_renewal(license_doc: Document, rule: RenewalRule,
                         passport: Document, passport_rule: RenewalRule,
                         today: date) -> Plan:
    window_days = rule.renewal_window_days_before_expiry or 90
    window_opens = license_doc.expiry - relativedelta(days=window_days)
    reasons = [
        f"license expires {license_doc.expiry.isoformat()}, renewal window opens {window_opens.isoformat()}",
        "renewal requires valid passport in hand",
    ]
    steps: list[PlanStep] = []
    conflicts: list[str] = []

    if today >= window_opens:
        steps.append(PlanStep("driver_license", "renew", license_doc.expiry, reasons))
    else:
        steps.append(PlanStep("driver_license", "prepare", window_opens, reasons))

    if passport_rule.surrenders_current:
        conflicts.append(
            "passport renewal requires surrendering the current passport to the consulate; "
            "while it is away, license renewal (which needs the passport in hand) is blocked. "
            "Sequence: renew the license before the passport appointment, or wait for the new passport."
        )
    return Plan(steps=steps, conflicts=conflicts)
