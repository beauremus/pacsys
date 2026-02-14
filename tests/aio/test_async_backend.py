"""Tests for AsyncBackend ABC contract."""

import pytest

from pacsys.aio._backends import AsyncBackend
from pacsys.types import BackendCapability


class ConcreteAsyncBackend(AsyncBackend):
    """Minimal concrete implementation for testing ABC."""

    @property
    def capabilities(self):
        return BackendCapability.READ

    async def read(self, drf, timeout=None):
        return 42.0

    async def get(self, drf, timeout=None):
        raise NotImplementedError

    async def get_many(self, drfs, timeout=None):
        raise NotImplementedError

    async def close(self):
        pass


class TestAsyncBackendABC:
    def test_cannot_instantiate_abc(self):
        with pytest.raises(TypeError):
            AsyncBackend()

    @pytest.mark.asyncio
    async def test_context_manager(self):
        async with ConcreteAsyncBackend() as b:
            assert b.capabilities == BackendCapability.READ

    @pytest.mark.asyncio
    async def test_write_raises_not_implemented(self):
        async with ConcreteAsyncBackend() as b:
            with pytest.raises(NotImplementedError):
                await b.write("M:OUTTMP", 1.0)

    @pytest.mark.asyncio
    async def test_subscribe_raises_not_implemented(self):
        async with ConcreteAsyncBackend() as b:
            with pytest.raises(NotImplementedError):
                await b.subscribe(["M:OUTTMP@p,1000"])

    def test_auth_defaults(self):
        b = ConcreteAsyncBackend()
        assert b.authenticated is False
        assert b.principal is None
