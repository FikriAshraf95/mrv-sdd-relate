# M03a plan

Steps for [M03a](M03a-booking-core.md): the slot grid first ([SPEC-03 §1](../../specs/SPEC-03-booking-rules.md#1-slots-and-opening-hours)), then the insert with its overlap check in one transaction ([SPEC-03 §3](../../specs/SPEC-03-booking-rules.md#3-overlap-rule)).

1. Build the grid in `src/booking/slots.py` from the court's opening hours.
2. Put the booking row in `src/booking/model.py` and the insert in the same module.
3. Write the overlap check in `src/booking/overlap.py` and call it inside the insert transaction, so a race has one winner.
4. Tests last, named after the checks.
