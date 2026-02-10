"""Log conversation state from Weave-instrumented realtime calls."""

import copy
import json
import weave
from weave.trace_server.trace_server_interface import CallsFilter
from weave.trace.serialization.serialize import to_json

from object_helpers import resolve_refs_recursive, unbox_recursive


@weave.op()
def get_traces_for_thread(client, thread_id: str):
    calls = client.get_calls(filter=CallsFilter(thread_ids=[thread_id]))
    return [c.trace_id for c in calls if c.trace_id is not None]


@weave.op()
def get_call_with_full_conversation(client, thread_id: str):
    """
    Given a thread containing a weave-instrumented realtime conversation,
    return the most recent call that contains the full conversation.
    """
    trace_ids = get_traces_for_thread(client, thread_id)
    calls = client.get_calls(filter=CallsFilter(trace_ids=trace_ids))

    realtime_calls_without_thread_id = [c for c in calls if c.thread_id is None]
    realtime_child_calls = [c for c in realtime_calls_without_thread_id if len(c.children()) == 0]
    if len(realtime_child_calls) == 0:
        return None

    last_call = max(realtime_child_calls, key=lambda x: x.ended_at)
    return last_call


@weave.op()
def remove_content_key_from_messages(messages: list[dict], content_key: str) -> None:
    """Remove a key from each message's content parts (e.g. 'audio' or 'transcript')."""
    for message in messages:
        if message.get("type") == "message" and "content" in message:
            for content in message["content"]:
                if content_key in content:
                    del content[content_key]


async def log_messages(logger, thread_id: str, call_id: str, messages: list[dict], total_message_size: int):
    """Perform the logging of messages to the given logger."""
    await logger.info(
        f"Idle | Messages | thread_id={thread_id} call_id={call_id} total_message_size={total_message_size} messages={messages}"
    )


@weave.op()
async def log_transcript_messages(logger, thread_id: str, call_id: str, messages: list[dict], messages_size: int):
    """Log messages (e.g. transcript form with audio removed) in original message structure."""
    await log_messages(logger, thread_id, call_id, messages, messages_size)


@weave.op()
async def log_audio_messages(logger, thread_id: str, call_id: str, messages: list[dict], messages_size: int):
    """Perform the logging of realtime (audio) messages to the given logger."""
    await log_messages(logger, thread_id, call_id, messages, messages_size)


@weave.op()
def extract_messages(client, call) -> list[dict]:
    """Convert a realtime call to a list of message dicts suitable for logging."""
    project_id = call.project_id
    messages = call.inputs["messages"] + call.output["output"]
    resolved_messages = resolve_refs_recursive(messages, client, project_id)
    unboxed_messages = unbox_recursive(resolved_messages)
    messages_for_log = to_json(unboxed_messages, project_id, client)
    return messages_for_log


@weave.op()
async def log_conversation(logger, thread_id: str | None) -> None:
    """Fetch calls for the given thread and log the most recent realtime conversation."""
    await logger.info(f"Idle | Logging conversation for thread_id={thread_id}")
    if thread_id is None:
        return
    try:
        client = weave.get_client()
        last_call = get_call_with_full_conversation(client, thread_id)
        if last_call is None:
            return

        messages_for_log = extract_messages(client, last_call)

        last_call_id = f"{last_call.id}"
        messages_for_transcript = copy.deepcopy(messages_for_log)
        remove_content_key_from_messages(messages_for_transcript, "audio")
        await log_transcript_messages(logger, thread_id, last_call_id, messages_for_transcript, len(json.dumps(messages_for_transcript).encode()))

        # remove transcripts before logging to demonstrate that the audio-based monitors are actually operating on audio
        remove_content_key_from_messages(messages_for_log, "transcript")
        await log_audio_messages(logger, thread_id, last_call_id, messages_for_log, len(json.dumps(messages_for_log).encode()))

    except Exception as e:
        await logger.error(f"Event | failed to get thread calls: {repr(e)}")
