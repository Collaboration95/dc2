from fastapi import Request

from processing.errors import ProcessingError


def gateway_actor(request: Request):
    """Resolve only adapter-injected identity; HTTP headers confer no authority."""
    from contracts.v1 import Actor, ContractError

    actor = getattr(request.state, "actor", None)
    if getattr(request.state, "gateway_v1", False) is not True or not isinstance(actor, Actor):
        raise ProcessingError(401, "Missing or invalid trusted context")
    try:
        Actor.from_context(actor.to_context())
    except ContractError as exc:
        raise ProcessingError(401, "Missing or invalid trusted context") from exc
    return actor
