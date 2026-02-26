"""MCP server exposing camera_on and camera_off tools to the agent.

The agent calls these tools to control the camera for visual observation
of the user during conversation. Tools close over a shared VisionPipeline.
"""

from __future__ import annotations

from typing import Any

from claude_agent_sdk import create_sdk_mcp_server, tool

from noaises.vision.pipeline import VisionPipeline

CAMERA_META_PROMPT = """\
## Camera / Vision

You have a camera you can control (camera_on, camera_off tools):
- **camera_on** — starts the camera so you can see the user. Use when visual context would help (reading emotions, seeing what they're showing you, etc.)
- **camera_off** — stops the camera when visual context is no longer needed.

While the camera is on, you'll receive visual observations of the user alongside their speech. Use these naturally — comment on what you see when relevant, but don't narrate every observation.
"""

CAMERA_TOOL_NAMES = [
    "mcp__camera__camera_on",
    "mcp__camera__camera_off",
]


def create_camera_mcp_server(vision_pipeline: VisionPipeline) -> Any:
    """Create an in-process MCP server with camera tools bound to *vision_pipeline*."""

    @tool(
        "camera_on",
        "Turn on the camera to see the user. Use when visual context would be helpful.",
        {"type": "object", "properties": {}},
    )
    async def camera_on(args: dict[str, Any]) -> dict[str, Any]:
        try:
            status = await vision_pipeline.start()
            return _ok(status)
        except Exception as e:
            return _ok(f"Camera failed to start: {e}")

    @tool(
        "camera_off",
        "Turn off the camera. Visual observations will stop.",
        {"type": "object", "properties": {}},
    )
    async def camera_off(args: dict[str, Any]) -> dict[str, Any]:
        try:
            status = await vision_pipeline.stop()
            return _ok(status)
        except Exception as e:
            return _ok(f"Camera failed to stop: {e}")

    return create_sdk_mcp_server(
        name="camera",
        version="1.0.0",
        tools=[camera_on, camera_off],
    )


def _ok(text: str) -> dict[str, Any]:
    return {"content": [{"type": "text", "text": text}]}
