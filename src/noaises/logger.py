import json
import sys
from datetime import datetime
from typing import Any, Literal

LogLevel = Literal["INFO", "WARN", "ERROR"]


def log(level: LogLevel, message: str, data: dict[str, Any] | None = None) -> None:
    """Log a message with optional structured data.

    Args:
        level: Log level (INFO, WARN, ERROR)
        message: Log message
        data: Optional structured data to include
    """
    timestamp = datetime.now().isoformat()
    log_message = f"[{timestamp}] [{level}] {message}"

    # Format data as JSON if present
    data_str = ""
    if data:
        try:
            data_str = " " + json.dumps(data, default=str)
        except (TypeError, ValueError):
            data_str = f" {data}"

    output = log_message + data_str

    stream = sys.stderr if level in ("ERROR", "WARN") else sys.stdout
    try:
        print(output, file=stream)
    except UnicodeEncodeError:
        # Windows cp1252 console can't encode some Unicode characters
        encoding = getattr(stream, "encoding", "utf-8") or "utf-8"
        safe = output.encode(encoding, errors="replace").decode(encoding, errors="replace")
        print(safe, file=stream)