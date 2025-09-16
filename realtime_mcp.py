import aiohttp
# Copyright (c) Microsoft Corporation.
# Licensed under the MIT license.

import asyncio
import base64
import json
import os
import queue
import sys
import time
import threading
import pyaudio
from dotenv import load_dotenv
from logger import Logger

logger = Logger(__name__)

load_dotenv()

import weave

from rtclient import (
    InputAudioBufferAppendMessage,
    InputAudioTranscription,
    RTLowLevelClient,
    ServerVAD,
    SessionUpdateMessage,
    SessionUpdateParams,
    ResponseCreateMessage,
    ResponseCreateParams,
    ItemCreateMessage,
    ResponseFunctionCallOutputItem,
    models,
)
from config import (
    INPUT_SAMPLE_RATE,
    INPUT_CHUNK_SIZE,
    OUTPUT_SAMPLE_RATE,
    OUTPUT_CHUNK_SIZE,
    STREAM_FORMAT,
    INPUT_CHANNELS,
    OUTPUT_CHANNELS,
    INSTRUCTIONS,
    VOICE_TYPE,
    TEMPERATURE,
    MAX_RESPONSE_OUTPUT_TOKENS,
    TOOLS,
    TOOL_CHOICE,
    TOOL_MAP
)
from logger import Logger
weave.init("realtime-chat-oai-5")

audio_input_queue = queue.Queue()
audio_output_queue = queue.Queue()
execute_tool_queue = asyncio.Queue()
client_event_queue = asyncio.Queue()

async def send_text_client_event(client: RTLowLevelClient):
    while True:
        message = await client_event_queue.get()
        await client.send(message)

async def send_message(client: RTLowLevelClient, data: dict):
    await client.send(json.dumps(data))

async def receive_messages(client: RTLowLevelClient):
    while True:
        message = await client.recv()
        if message is None:
            continue
        match message.type:
            case "session.created":
                await logger.info(f"Server | session.created | model: {message.session.model}, session_id: {message.session.id}")
            case "error":
                await logger.info(f"Server | error | error message:{message.error}")
            case "input_audio_buffer.committed":
                await logger.info(f"Server | input_audio_buffer.committed | item_id:{message.item_id}")
                pass
            case "input_audio_buffer.cleared":
                await logger.info(f"Server | input_audio_buffer.cleared | event_id: {message.event_id}")
                pass
            case "input_audio_buffer.speech_started":
                await logger.info(f"Server | input_audio_buffer.speech_started | item_id: {message.item_id}, audio_start_ms: {message.audio_start_ms}")
                while not audio_output_queue.empty():
                    audio_output_queue.get()
                await asyncio.sleep(0)
            case "input_audio_buffer.speech_stopped":
                await logger.info(f"Server | input_audio_buffer.speech_stopped | item_id: {message.item_id}, audio_end_ms: {message.audio_end_ms}")
                pass
            case "conversation.item.created":
                await logger.info(f"Server | conversation.item.created | item_id: {message.item.id}, previous_item_id: {message.previous_item_id}")
            case "conversation.item.truncated":
                await logger.info(f"Server | conversation.item.truncated | item_id: {message.item_id}, content_index: {message.content_index}, audio_end_ms: {message.audio_end_ms}")
            case "conversation.item.deleted":
                await logger.info(f"Server | conversation.item.deleted | item_id: {message.item_id}")
            case "conversation.item.input_audio_transcription.completed":
                await logger.info(f"Server | conversation.item.input_audio_transcription.completed | item_id: {message.item_id}, content_index: {message.content_index}, transcript: {message.transcript}")
            case "conversation.item.input_audio_transcription.failed":
                await logger.info(f"Server | conversation.item.input_audio_transcription.failed | item_id: {message.item_id}, error: {message.error}")
            case "conversation.item.input_audio_transcription.delta":
                await logger.info(f"Server | conversation.item.input_audio_transcription.delta | item_id: {message.item_id}, delta: {message.delta}")
            case "response.created":
                await logger.info(f"Server | response.created | response_id: {message.response.id}")
            case "response.done":
                await logger.info(f"Server | response.done | response_id: {message.response.id}")
                pass
            case "response.output_item.added":
                await logger.info(f"Server | response.output_item.added | response_id: {message.response_id}, item_id: {message.item.id}")
            case "response.output_item.done":
                if message.item.type == "mcp_call":
                    await client.send(json.dumps({"type": "response.create"}))
                await logger.info(f"Server | response.output_item.done | response_id: {message.response_id}, item_id: {message.item.id}")
            case "response.content_part.added":
                await logger.info(f"Server | response.content_part.added | response_id: {message.response_id}, item_id: {message.item_id}")
            case "response.content_part.done":
                await logger.info(f"Server | response.content_part.done | response_id: {message.response_id}, item_id: {message.item_id}")
            case "response.text.delta":
                await logger.info(f"Server | response.text.delta | response_id: {message.response_id}, item_id: {message.item_id}, text: {message.delta}")
            case "response.text.done":
                await logger.info(f"Server | response.text.done | response_id: {message.response_id}, item_id: {message.item_id}, text: {message.text}")
            case "response.audio_transcript.delta":
                await logger.info(f"Server | response.audio_transcript.delta | response_id: {message.response_id}, item_id: {message.item_id}, transcript: {message.delta}")
            case "response.audio_transcript.done":
                await logger.info(f"Server | response.audio_transcript.done | response_id: {message.response_id}, item_id: {message.item_id}, transcript: {message.transcript}")
            case "response.audio.delta":
                await logger.info(f"Server | response.audio.delta | response_id: {message.response_id}, item_id: {message.item_id}, audio_data_length: {len(message.delta)}")
                audio_data = base64.b64decode(message.delta)
                for i in range(0, len(audio_data), OUTPUT_CHUNK_SIZE):
                    audio_output_queue.put(audio_data[i:i+OUTPUT_CHUNK_SIZE])
                await asyncio.sleep(0)
            case "response.audio.done":
                await logger.info(f"Server | response.audio.done | response_id: {message.response_id}, item_id: {message.item_id}")
            case "response.function_call_arguments.delta":
                await logger.info(f"Server | response.function_call_arguments.delta | response_id: {message.response_id}, item_id: {message.item_id}, arguments: {message.delta}")
            case "response.function_call_arguments.done":
                await logger.info(f"Server | response.function_call_arguments.done | response_id: {message.response_id}, item_id: {message.item_id}, arguments: {message.arguments}")
                fn = TOOL_MAP[message.name]
                result = fn(**json.loads(message.arguments))
                call_id = message.call_id
                result = {
                    "type": "conversation.item.create",
                    "item": {
                        "type": "function_call_output",
                        "call_id": call_id,
                        "output": json.dumps(result)
                    }
                }
                await client.send(json.dumps(result))
                await client.send(json.dumps({"type": "response.create"}))

            case "rate_limits.updated":
                await logger.info(f"Server | rate_limits.updated | rate_limits: {message.rate_limits}")
            case _:
                await logger.info(f"Server | {message.type}")

def listen_audio(input_stream: pyaudio.Stream):
    while True:
        audio_data = input_stream.read(INPUT_CHUNK_SIZE, exception_on_overflow=False)
        if audio_data is None:
            continue
        base64_audio = base64.b64encode(audio_data).decode("utf-8")
        audio_input_queue.put(base64_audio)

async def send_audio(client: RTLowLevelClient):
    while not client.closed:
        base64_audio = await asyncio.get_event_loop().run_in_executor(None, audio_input_queue.get)
        await logger.info("Client | input_audio_buffer.append")
        await client.send(InputAudioBufferAppendMessage(audio=base64_audio))
        await asyncio.sleep(0)

def play_audio(output_stream: pyaudio.Stream):
    while True:
        audio_data = audio_output_queue.get()
        output_stream.write(audio_data)

async def with_openai():
    key = os.environ.get("OPENAI_API_KEY") or ""
    model = os.environ.get("OPENAI_MODEL") or "gpt-realtime"

    p = pyaudio.PyAudio()
    input_default_input_index = int(p.get_default_input_device_info()['index'])
    input_stream = p.open(
        format=STREAM_FORMAT,
        channels=INPUT_CHANNELS,
        rate=INPUT_SAMPLE_RATE,
        input=True,
        output=False,
        frames_per_buffer=INPUT_CHUNK_SIZE,
        input_device_index=input_default_input_index,
        start=False,
    )
    output_default_output_index = int(p.get_default_output_device_info()['index'])
    output_stream = p.open(
        format=STREAM_FORMAT,
        channels=OUTPUT_CHANNELS,
        rate=OUTPUT_SAMPLE_RATE,
        input=False,
        output=True,
        frames_per_buffer=OUTPUT_CHUNK_SIZE,
        output_device_index=output_default_output_index,
        start=False,
    )
    input_stream.start_stream()
    output_stream.start_stream()

    print("Start Processing")
    async with RTLowLevelClient(model=model) as client:
        await logger.info("Client | session.update")
        await client.send(
            SessionUpdateMessage(
                session=SessionUpdateParams(
                    model=model,
                    modalities={"text", "audio"},
                    input_audio_format="pcm16",
                    output_audio_format="pcm16",
                    turn_detection=ServerVAD(type="server_vad", threshold=0.5, prefix_padding_ms=200, silence_duration_ms=200),
                    input_audio_transcription=InputAudioTranscription(model="whisper-1"),
                    voice=VOICE_TYPE,
                    instructions=INSTRUCTIONS,
                    temperature=TEMPERATURE,
                    max_response_output_tokens=MAX_RESPONSE_OUTPUT_TOKENS,
                    tools=TOOLS,
                    tool_choice=TOOL_CHOICE,
                )
            )
        )
        print(
            SessionUpdateMessage(
                session=SessionUpdateParams(
                    model=model,
                    modalities={"text", "audio"},
                    input_audio_format="pcm16",
                    output_audio_format="pcm16",
                    turn_detection=ServerVAD(type="server_vad", threshold=0.5, prefix_padding_ms=200, silence_duration_ms=200),
                    input_audio_transcription=InputAudioTranscription(model="whisper-1"),
                    voice=VOICE_TYPE,
                    instructions=INSTRUCTIONS,
                    temperature=TEMPERATURE,
                    max_response_output_tokens=MAX_RESPONSE_OUTPUT_TOKENS,
                    tools=TOOLS,
                    tool_choice=TOOL_CHOICE,
                )
            )
        )

        threading.Thread(target=listen_audio, args=(input_stream,), daemon=True).start()
        threading.Thread(target=play_audio, args=(output_stream,), daemon=True).start()
        send_audio_task = asyncio.create_task(send_audio(client))
        receive_task = asyncio.create_task(receive_messages(client))

        send_text_client_event_task = asyncio.create_task(send_text_client_event(client))

        await asyncio.gather(send_audio_task, receive_task, send_text_client_event_task)

async def main():
    await with_openai()

if __name__ == "__main__":
    asyncio.run(main())
