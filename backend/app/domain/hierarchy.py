"""Leadership hierarchy rules (F7 / delta-007).

The hierarchy is the `pessoas.lider_id` chain: each person points to the person
who leads them. Cell-edit authorization (delta-007) requires the acting user to
be either the cell's own leader or someone *above* that leader in the chain.

`is_leader_or_superior` is pure: it receives a parent-lookup mapping
(`lider_of`: pessoa_id -> lider_id) and walks upward from the cell leader,
returning True when it reaches the acting person. A configurable depth guard
prevents infinite loops on malformed (cyclic) data.
"""

from __future__ import annotations

from collections.abc import Mapping

_MAX_DEPTH = 64


def is_leader_or_superior(
    *,
    actor_pessoa_id: str | None,
    cell_leader_id: str | None,
    lider_of: Mapping[str, str | None],
) -> bool:
    """True if `actor_pessoa_id` leads, directly or transitively, the cell.

    - The actor being the cell's own leader counts as authorized.
    - Walking up `lider_of` from the cell leader, any ancestor equal to the
      actor authorizes the edit.
    - Returns False when the actor has no linked person or the cell has no
      leader to anchor the chain.
    """
    if not actor_pessoa_id or not cell_leader_id:
        return False

    current: str | None = cell_leader_id
    seen: set[str] = set()
    depth = 0
    while current is not None and depth < _MAX_DEPTH:
        if current == actor_pessoa_id:
            return True
        if current in seen:  # cycle guard
            break
        seen.add(current)
        current = lider_of.get(current)
        depth += 1
    return False
