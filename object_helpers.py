from copy import deepcopy
from typing import Any
from weave.trace import box
from weave.trace.refs import Ref
from weave.trace.serialization.serialize import from_json
from weave.trace_server.trace_server_interface import RefsReadBatchReq


def _collect_refs(obj: Any, out: list[Ref] | None = None) -> list[Ref]:
    """Recursively collect all Ref instances in a structure."""
    if out is None:
        out = []
    if isinstance(obj, Ref):
        out.append(obj)
        return out
    if isinstance(obj, dict):
        for v in obj.values():
            _collect_refs(v, out)
        return out
    if isinstance(obj, (list, tuple)):
        for v in obj:
            _collect_refs(v, out)
        return out
    return out


def _replace_refs_in_obj(obj: Any, uri_to_val: dict[str, Any]) -> Any:
    """Build a copy of the structure with refs replaced by resolved values."""
    if isinstance(obj, Ref):
        uri = obj.uri()
        if uri in uri_to_val:
            return uri_to_val[uri]
        return obj
    if isinstance(obj, dict):
        return {k: _replace_refs_in_obj(v, uri_to_val) for k, v in obj.items()}
    if isinstance(obj, list):
        return [_replace_refs_in_obj(v, uri_to_val) for v in obj]
    if isinstance(obj, tuple):
        return tuple(_replace_refs_in_obj(v, uri_to_val) for v in obj)
    return obj


def resolve_refs_recursive(
    obj: Any,
    client: "WeaveClient",
    project_id: str,
    max_rounds: int = 20,
) -> Any:
    """Resolve all refs (CallRef, ObjectRef, etc.) in a structure via refs_read_batch."""
    from weave.trace.weave_client import WeaveClient  # or your client type

    server = client.server
    current = deepcopy(obj)
    for _ in range(max_rounds):
        refs = _collect_refs(current)
        if not refs:
            return current
        # Dedupe by URI so we only request each ref once per round
        uris = list(dict.fromkeys(r.uri() for r in refs))
        res = server.refs_read_batch(RefsReadBatchReq(refs=uris))
        uri_to_val = dict(zip(uris, res.vals))
        # Re-parse resolved vals so nested "weave://" become Ref and get resolved next round
        for uri, val in uri_to_val.items():
            if isinstance(val, (dict, list)):
                uri_to_val[uri] = from_json(val, project_id, server)
        current = _replace_refs_in_obj(current, uri_to_val)
    return current


def unbox_recursive(obj: Any) -> Any:
    """Recursively unbox BoxedStr/BoxedInt/etc. so no .ref is left for the tracer to serialize."""
    v = box.unbox(obj)
    if isinstance(v, dict):
        return {k: unbox_recursive(x) for k, x in v.items()}
    if isinstance(v, list):
        return [unbox_recursive(x) for x in v]
    if isinstance(v, tuple):
        return tuple(unbox_recursive(x) for x in v)
    return v
