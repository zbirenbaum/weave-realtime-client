import datetime
from typing_extensions import Callable
import pyaudio
import os
import dotenv
from zoneinfo import ZoneInfo
dotenv.load_dotenv()

GH_PAT = os.environ.get("GH_PAT") or ""

INPUT_SAMPLE_RATE = 24000  # Input sample rate
INPUT_CHUNK_SIZE = 2048  # Input chunk size
OUTPUT_SAMPLE_RATE = 24000  # Output sample rate. ** Note: This must be 24000 **
OUTPUT_CHUNK_SIZE = 2048 # Output chunk size
STREAM_FORMAT = pyaudio.paInt16  # Stream format
INPUT_CHANNELS = 1  # Input channels
OUTPUT_CHANNELS = 1  # Output channels
OUTPUT_SAMPLE_WIDTH = 2  # Output sample width

INSTRUCTIONS="""You are a helpful developer assistant for the github user zbirenbaum.
zbirenbaum may ask you for information regarding his own repositories
(such as zbirenbaum/copilot.lua) or his weights and biases work repositories.
The weights and biases org is 'wandb' and has public repos such as 'weave' (wandb/weave)
"""
VOICE_TYPE = "shimmer"  # alloy, echo, shimmer
TEMPERATURE = 0.7
MAX_RESPONSE_OUTPUT_TOKENS = 4096

TOOLS = [
    # {
    #     "type": "mcp",
    #     "server_label": "aws-api",
    #     "server_url": "http://127.0.0.1:8011/mcp",
    #     "require_approval": "never",
    #     "allowed_tools": ['call_aws', 'suggest_aws_commands']
    # },
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

TOOL_MAP = {
    "get_current_datetime": get_current_datetime
}
