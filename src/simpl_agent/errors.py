"""Errors shared by the server and its tool modules.

Kept in its own module so there is exactly one ToolError class even when the
server runs as ``python -m simpl_agent.server`` (where server.py is loaded as
``__main__`` and a class defined there would differ from the imported one).
"""


class ToolError(Exception):
    """A request the tool refuses; reported to the client, never a crash."""
