import pytest
import asyncio

from translator.utils.utils_async import run_with_retries


@pytest.mark.asyncio
async def test_run_with_retries_success():
    async def succeed(x):
        return x + 1

    assert await run_with_retries(succeed, 41) == 42


@pytest.mark.asyncio
async def test_run_with_retries_failure():
    async def failer(*a, **k):
        raise ValueError("fail!")

    with pytest.raises(ValueError):
        await run_with_retries(failer, 0, attempts=2)
