# This file is a parse fixture, not executable Python.
# Imports are intentionally omitted. Do not add them.
"""Test fixture: calls from async functions."""


async def fetch_data(url):
    """Fetch data from URL."""
    result = await helper()
    return result


async def helper():
    """Helper function."""
    return "data"


class AsyncClient:
    """Async client class."""

    async def get(self, url):
        """GET request."""
        data = await self.fetch(url)
        return data

    async def fetch(self, url):
        """Fetch URL."""
        return await helper()

    async def post(self, url, data):
        """POST request."""
        await self.get(url)
        await helper()
