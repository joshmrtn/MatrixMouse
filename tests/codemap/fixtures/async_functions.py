# This file is a parse fixture, not executable Python.
# Imports are intentionally omitted. Do not add them.
"""Test fixture: async functions and methods."""


async def fetch(url):
    """An async function."""
    result = await get(url)
    return result


class Client:
    """An async client."""

    async def post(self, data):
        """An async method."""
        await send(data)
