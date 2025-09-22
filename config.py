import base64
import datetime
import mimetypes
import os
from typing import List, Optional, TypedDict
from typing import Any
from zoneinfo import ZoneInfo
import dotenv
import pyaudio
dotenv.load_dotenv()

GH_PAT = os.environ.get("GH_PAT") or None

INPUT_SAMPLE_RATE = 24000  # Input sample rate
INPUT_CHUNK_SIZE = 2048  # Input chunk size
OUTPUT_SAMPLE_RATE = 24000  # Output sample rate. ** Note: This must be 24000 **
OUTPUT_CHUNK_SIZE = 2048 # Output chunk size
STREAM_FORMAT = pyaudio.paInt16  # Stream format
INPUT_CHANNELS = 1  # Input channels
OUTPUT_CHANNELS = 1  # Output channels
OUTPUT_SAMPLE_WIDTH = 2  # Output sample width


WEAVE_PROJECT=os.environ.get("WEAVE_PROJECT", "realtime-example")
INSTRUCTIONS=os.environ.get("INSTRUCTIONS", "You are a helpful developer assistant")
VOICE_TYPE = "marin"
TEMPERATURE = 0.7
MAX_RESPONSE_OUTPUT_TOKENS = 4096

TOOLS = [
    {
        "type": "mcp",
        "server_label": "github",
        "server_url": "https://api.githubcopilot.com/mcp/",
        "authorization": GH_PAT,
        "require_approval": "never",
        "allowed_tools": ['list_pull_requests']
    },
    {
        "type": "function",
        "name": "get_current_datetime",
        "description": "Get the current date and time",
        "parameters": {
            "type": "object",
            "properties": {
                "timezone": {
                    "type": "string",
                    "description": "The timezone to get the time for",
                    "enum": ["local", "UTC", "EST", "PST"]
                }
            },
            "required": ["timezone"]
        }
    },
    {
        "type": "function",
        "name": "add_numbers",
        "description": "Add numbers together and return their sum.",
        "parameters": {
            "type": "object",
            "properties": {
                "numbers": {
                    "type": "array",
                    "description": "List of numbers to add together.",
                    "items": {"type": "number"}
                },
                "a": {"type": "number", "description": "First addend (optional if numbers provided)"},
                "b": {"type": "number", "description": "Second addend (optional if numbers provided)"}
            },
            "required": []
        }
    },
    {
        "type": "function",
        "name": "list_files",
        "description": "List files in the current directory and subdirectories.",
        "parameters": {
            "type": "object",
            "properties": {
                "root": {"type": "string", "description": "Root directory to start from", "default": "."},
                "max_results": {"type": "integer", "description": "Maximum number of files to return", "default": 500},
                "include_hidden": {"type": "boolean", "description": "Whether to include hidden files and directories", "default": False},
                "extensions": {"type": "array", "description": "Optional list of file extensions to include (e.g. ['.png','.jpg'])", "items": {"type": "string"}}
            },
            "required": []
        }
    },
    {
        "type": "function",
        "name": "get_image_file_by_path",
        "description": "Read an image by path and attach it to the conversation as an input_image containing a data URL.",
        "parameters": {
            "type": "object",
            "properties": {
                "path": {"type": "string", "description": "Absolute or relative path to the image file."},
                "inline_limit_bytes": {"type": "integer", "description": "Max bytes to inline; larger files will be truncated.", "default": 1048576}
            },
            "required": ["path"]
        }
    }
]

TOOL_CHOICE = "auto"

def get_current_datetime(timezone: str):
    if timezone == "local":
        current_time = datetime.datetime.now()
    else:
        current_time = datetime.datetime.now(ZoneInfo(timezone))
    return {
        "datetime": current_time.strftime("%Y-%m-%d %H:%M:%S"),
        "timezone": timezone,
        "day_of_week": current_time.strftime("%A")
    }

def add_numbers(numbers: Optional[List[float]] = None, a: Optional[float] = None, b: Optional[float] = None):
    if numbers is None:
        numbers = []
        if a is not None:
            numbers.append(a)
        if b is not None:
            numbers.append(b)
    total = float(sum(numbers))
    return {"sum": total, "operands": numbers}


def list_files(root: str = ".", max_results: int = 500, include_hidden: bool = False, extensions: Optional[List[str]] = None):
    root = os.path.abspath(root)
    results: List[str] = []
    for dirpath, dirnames, filenames in os.walk(root):
        if not include_hidden:
            # Filter hidden directories in-place to prevent walking into them
            dirnames[:] = [d for d in dirnames if not d.startswith('.')]
            filenames = [f for f in filenames if not f.startswith('.')]
        for fname in filenames:
            if extensions:
                try:
                    ext = os.path.splitext(fname)[1].lower()
                except Exception:
                    ext = ""
                if ext not in [e.lower() for e in extensions]:
                    continue
            full_path = os.path.join(dirpath, fname)
            try:
                rel_path = os.path.relpath(full_path, start=os.getcwd())
            except Exception:
                rel_path = full_path
            results.append(rel_path)
            if len(results) >= max_results:
                return {"root": root, "count": len(results), "files": results, "truncated": True}
    return {"root": root, "count": len(results), "files": results, "truncated": False}


def get_image_file_by_path(path: str, inline_limit_bytes: int = 1024 * 1024*10):
    abs_path = os.path.abspath(path)
    if not os.path.exists(abs_path):
        return {"ok": False, "error": f"File not found: {path}"}
    if not os.path.isfile(abs_path):
        return {"ok": False, "error": f"Not a file: {path}"}

    mime, _ = mimetypes.guess_type(abs_path)
    if not mime or not mime.startswith("image/"):
        return {"ok": False, "error": f"Unsupported or unknown image type for: {path}"}

    try:
        with open(abs_path, "rb") as f:
            data = f.read()
    except Exception as e:
        return {"ok": False, "error": f"Failed to read file: {e}"}

    is_truncated = False
    if len(data) > inline_limit_bytes:
        data = data[:inline_limit_bytes]
        is_truncated = True

    b64 = base64.b64encode(data).decode("utf-8")
    data_url = f"data:{mime};base64,{b64}"

    # Provide a user_item request that the runtime can translate into a conversation item
    # Use the new input_image content part instead of embedding the data URL in input_text.
    user_item = {
        "type": "message",
        "role": "user",
        "content": [
            {
                "type": "input_image",
                "image_url": data_url,
            }
        ]
    }

    return {
        "ok": True,
        "path": os.path.relpath(abs_path, start=os.getcwd()),
        "mime": mime,
        "bytes_included": len(data),
        "truncated": is_truncated,
        "user_item": user_item,
    }

TOOL_MAP = {
    "get_current_datetime": get_current_datetime,
    "add_numbers": add_numbers,
    "list_files": list_files,
    # "get_image_file_by_path": get_image_file_by_path,
}
