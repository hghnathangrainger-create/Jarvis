"""
schedule_compound_workflow.py

The exact trusted recognizer for the second Phase 99 compound template
(Batch 1, dormant - docs/phase_99_second_compound_template_planning.md):
SCHEDULE_ENABLE -> SCHEDULE_VERIFY_ENABLED_STATE -> SCHEDULE_SHOW_ENABLED_STATE.

Mirrors core/compound_workflow.py's own matches_compound_plan_shape()
exactly in spirit - a narrow, hand-authored structural fingerprint,
never a generic "any write-verify-read sequence" acceptance - but is
its own, wholly separate, parallel module: core/compound_workflow.py's
own recognizer, progress-creation, claimed-recovery, and translator
logic all remain untouched by this batch, and this module is never
imported by them, by core/orchestrator.py, or by main.py in Batch 1.

Responsibilities:
    - Recognize a Plan as the exact trusted schedule-compound
      fingerprint - never merely "three steps naming schedule
      capabilities." Every one of the following must hold exactly:
      three steps; step 1 is exactly SCHEDULE_ENABLE (never
      SCHEDULE_DISABLE); step 2 is exactly SCHEDULE_VERIFY_ENABLED_STATE;
      step 3 is exactly SCHEDULE_SHOW_ENABLED_STATE (never SCHEDULE_LIST
      or any other read capability); every step's own tool_input is
      exactly {"schedule_id": <int>} - no additional key, no omitted
      key; the identical schedule_id integer appears in all three
      steps; step 3's requires_verified_predecessor is True, its
      verification_field_name is exactly "enabled_str", and its
      verification_expected_value is exactly "true" (never "false" -
      no SCHEDULE_DISABLE-paired template exists yet); and every step's
      own stored tier matches its capability's declared
      max_execution_tier exactly (YELLOW, GREEN, GREEN).

Does NOT:
    - Get imported by intelligence/planning.py, core/orchestrator.py, or
      main.py in Batch 1 - only this module's own dedicated tests
      import it.
    - Establish progress, validate an approval, recover a claimed
      workflow, or translate a result - Foundations mirroring
      core/compound_workflow.py's own F/G/H/I are Batch 2's own,
      separately-approved scope, not this batch's.
    - Accept SCHEDULE_DISABLE in step 1's place, SCHEDULE_LIST in step
      3's place, a differing schedule_id across steps, an extra or
      missing tool_input key, or any three-step plan shape beyond this
      one hand-authored fingerprint.
"""

from __future__ import annotations

from intelligence.capability_catalog import CAPABILITY_CATALOG, CapabilityId
from planner.plan_models import Plan

_WRITE_CAPABILITY_ID = CapabilityId.SCHEDULE_ENABLE
_VERIFY_CAPABILITY_ID = CapabilityId.SCHEDULE_VERIFY_ENABLED_STATE
_SHOW_CAPABILITY_ID = CapabilityId.SCHEDULE_SHOW_ENABLED_STATE


def matches_schedule_compound_plan_shape(plan: Plan) -> bool:
    """The exact trusted fingerprint for the second Phase 99 compound
    template.

    Args:
        plan: The Plan to check - already reconstructed by the caller
            (from a live paused workflow, a freshly-built trusted plan,
            or a raw persisted record).

    Returns:
        True only if every structural requirement holds exactly. False
        for any mismatch, including an otherwise-arbitrary three-step
        plan naming schedule capabilities in some other combination or
        order.
    """
    steps = plan.steps
    if len(steps) != 3:
        return False
    step1, step2, step3 = steps

    write_adapter = CAPABILITY_CATALOG.get(_WRITE_CAPABILITY_ID)
    verify_adapter = CAPABILITY_CATALOG.get(_VERIFY_CAPABILITY_ID)
    show_adapter = CAPABILITY_CATALOG.get(_SHOW_CAPABILITY_ID)
    if write_adapter is None or verify_adapter is None or show_adapter is None:
        return False

    # Step 1: exactly SCHEDULE_ENABLE (never SCHEDULE_DISABLE, which
    # has a different tool_name entirely), exactly one key
    # ("schedule_id", a real, non-bool int), exact YELLOW tier.
    if step1.tool_name != write_adapter.tool_name:
        return False
    if set(step1.tool_input) != {"schedule_id"}:
        return False
    approved_schedule_id = step1.tool_input.get("schedule_id")
    if not isinstance(approved_schedule_id, int) or isinstance(
        approved_schedule_id, bool
    ):
        return False
    if step1.tier is not write_adapter.max_execution_tier:
        return False

    # Step 2: exactly SCHEDULE_VERIFY_ENABLED_STATE, exactly one key
    # ("schedule_id", identical to step 1's), exact GREEN tier.
    if step2.tool_name != verify_adapter.tool_name:
        return False
    if set(step2.tool_input) != {"schedule_id"}:
        return False
    if step2.tool_input.get("schedule_id") != approved_schedule_id:
        return False
    if step2.tier is not verify_adapter.max_execution_tier:
        return False

    # Step 3: exactly SCHEDULE_SHOW_ENABLED_STATE (never SCHEDULE_LIST
    # or any other read capability), exactly one key ("schedule_id",
    # identical to steps 1/2), exact GREEN tier, gated on a verified
    # predecessor expecting exactly "true" for the "enabled_str" field.
    if step3.tool_name != show_adapter.tool_name:
        return False
    if set(step3.tool_input) != {"schedule_id"}:
        return False
    if step3.tool_input.get("schedule_id") != approved_schedule_id:
        return False
    if step3.tier is not show_adapter.max_execution_tier:
        return False
    if not step3.requires_verified_predecessor:
        return False
    if step3.verification_field_name != "enabled_str":
        return False
    if step3.verification_expected_value != "true":
        return False

    return True
