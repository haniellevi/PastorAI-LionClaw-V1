"""Pure pastoral-domain logic (no I/O).

These modules hold the business rules of the pastoral core — phone
normalization, the person pipeline state machine (F2), the leadership
hierarchy (F7) and work-queue role gating (delta-006). Keeping them free of
database access makes the rules deterministic and unit-testable, while routers
stay thin controllers wiring HTTP <-> persistence.
"""
