"""Log conversation state from Weave-instrumented realtime calls."""

import copy
import json
from datetime import datetime, timezone

import weave
from weave.trace_server.trace_server_interface import CallsFilter
from weave.trace.serialization.serialize import to_json

from weave.trace import box


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
    calls = client.get_calls(
        filter=CallsFilter(trace_ids=trace_ids),
    )

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


async def log_messages_to_console(logger, thread_id: str, call_id: str, messages: list[dict], total_message_size: int):
    """Perform the logging of messages to the given logger."""
    await logger.info(
        f"Idle | Messages | thread_id={thread_id} call_id={call_id} total_message_size={total_message_size} messages={messages}"
    )


@weave.op()
async def log_transcript_messages(logger, thread_id: str, call_id: str, messages: list[dict], messages_size: int):
    """Log messages (e.g. transcript form with audio removed) in original message structure."""
    await log_messages_to_console(logger, thread_id, call_id, messages, messages_size)

    # Make the call look like a realtime API so that we can see a chat tab in the Weave UI
    return { "output": [] }


@weave.op()
async def log_audio_messages(logger, thread_id: str, call_id: str, messages: list[dict], messages_size: int):
    """Perform the logging of realtime (audio) messages to the given logger."""
    await log_messages_to_console(logger, thread_id, call_id, messages, messages_size)

    # Make the call look like a realtime API so that we can see a chat tab in the Weave UI
    return { "output": [] }


@weave.op()
async def log_messages(logger, thread_id: str, call_id: str, messages: list[dict]):
    messages_with_transcript_only = copy.deepcopy(messages)
    remove_content_key_from_messages(messages_with_transcript_only, "audio")
    await log_transcript_messages(logger, thread_id, call_id, messages_with_transcript_only, len(json.dumps(messages_with_transcript_only).encode()))

    # Remove transcripts before logging to demonstrate that the audio-based monitors are actually operating on audio
    messages_with_audio_only = copy.deepcopy(messages)
    remove_content_key_from_messages(messages_with_audio_only, "transcript")
    await log_audio_messages(logger, thread_id, call_id, messages_with_audio_only, len(json.dumps(messages_with_audio_only).encode()))
    
    # Make the call look like a realtime API so that we can see a chat tab in the Weave UI
    return { "output": [] }


@weave.op()
def extract_messages(client, call) -> list[dict]:
    """Convert a realtime call to a list of message dicts suitable for logging."""
    messages = call.inputs["messages"] + call.output["output"]
    messages_for_log = to_json(messages, call.project_id, client)
    return messages_for_log


def validate_call(call) -> bool:
    if "messages" not in call.inputs or "output" not in call.output:
        return False
    ended_at = getattr(call, "ended_at", None)
    if ended_at is None:
        return False
    now = datetime.now(timezone.utc)
    if ended_at.tzinfo is None:
        ended_at = ended_at.replace(tzinfo=timezone.utc)
    if (now - ended_at).total_seconds() < 5:
        return False
    return True

@weave.op()
async def log_conversation(logger, thread_id: str | None) -> False:
    """Fetch calls for the given thread and log the most recent realtime conversation."""
    await logger.info(f"Idle | Logging conversation for thread_id={thread_id}")
    if thread_id is None:
        return
    try:
        client = weave.get_client()
        last_call = get_call_with_full_conversation(client, thread_id)
        if last_call is None:
            return

        if not validate_call(last_call):
            return False

        messages = extract_messages(client, last_call)
        await log_messages(logger, thread_id, f"{last_call.id}", messages)

        return True

    except Exception as e:
        await logger.error(f"Event | failed to get thread calls: {repr(e)}")

    return False
