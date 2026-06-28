import pytest
import asyncio
import types
from unittest.mock import MagicMock
from pyrogram.client import Client
from anthropic import Anthropic
from telegram.ext import Application, ApplicationBuilder
from translator.services.telegram_sender import TelegramSender
from translator.services.event_logger import EventRecorder
from translator import bot


def test_import_bot_module():
    # Just import, should not crash
    import translator.bot


def test_init_clients_smoke(monkeypatch):
    # Patch out external dependencies and constructor side effects
    class DummyClient(Client):
        def __init__(self, *args, **kwargs):
            pass

    class DummyAnthropic(Anthropic):
        def __init__(self, *args, **kwargs):
            pass

    class DummySender(TelegramSender):
        def __init__(self):
            pass

    class DummyEventRecorder(EventRecorder):
        def __init__(self):
            pass

    class DummyBuilder(ApplicationBuilder):
        def __init__(self):
            pass
            
        def token(self, token):
            return self

        def rate_limiter(self, rl):
            return self

        def build(self):
            return DummyApp()

    class DummyApp(Application):
        def __init__(self):
            pass
            
        @classmethod
        def builder(cls):
            return DummyBuilder()

    monkeypatch.setattr(bot, "Client", DummyClient)
    monkeypatch.setattr(bot, "Application", DummyApp)
    monkeypatch.setattr(bot, "Anthropic", DummyAnthropic)
    monkeypatch.setattr(bot, "TelegramSender", DummySender)
    monkeypatch.setattr(bot, "EventRecorder", DummyEventRecorder)

    pyro, ptb_app, anthropic, sender, recorder = bot.init_clients()
    assert all(x is not None for x in (pyro, ptb_app, anthropic, sender, recorder))


def test_register_handlers_runs(monkeypatch):
    # Create dummy dependencies with required methods
    class DummyPyro(Client):
        def __init__(self):
            # Skip parent init
            pass
            
        def on_message(self, filt):
            def deco(fn):
                return fn
            return deco
            
        def on_edited_message(self, filt):
            def deco(fn):
                return fn
            return deco

    class DummyAnthropic(Anthropic):
        def __init__(self):
            # Skip parent init
            pass

    class DummySender(TelegramSender):
        def __init__(self):
            # Skip parent init but set required attributes
            self.configs = {}
            self.MAX_MESSAGE_LENGTH = 4096

    class DummyEventRecorder(EventRecorder):
        def __init__(self):
            # Skip parent init but set required attributes
            self.set = MagicMock()
            self.get = MagicMock(return_value="test")
            self.finalize = MagicMock()
            self.stats = {"messages": []}
            self.payload = {}

    # Create proper dummy filter class that supports & operator
    class DummyFilter:
        def __init__(self, return_value=True):
            self.return_value = return_value
            
        def __call__(self, *args, **kwargs):
            return self.return_value
            
        def __and__(self, other):
            return self  # For testing, just return self

    # Create dummy filters that act like Pyrogram filters
    channel_filter = DummyFilter()
    def chat_filter(ids):
        return DummyFilter()
        
    monkeypatch.setattr(bot.filters, "channel", channel_filter)
    monkeypatch.setattr(bot.filters, "chat", chat_filter)
    
    # Mock Config.get_source_channel_ids to return a list
    monkeypatch.setattr(bot.CONFIG, "get_source_channel_ids", lambda: [1, 2, 3])

    # Should not crash
    bot.register_handlers(DummyPyro(), DummyAnthropic(), DummySender(), DummyEventRecorder())


@pytest.mark.asyncio
async def test_ptb_worker_empty(monkeypatch):
    class DummyBot:
        async def get_chat(self, chat_id):
            return types.SimpleNamespace(
                to_dict=lambda: {"id": chat_id, "title": "t"}, username="user"
            )

        async def get_file(self, file_id):
            return types.SimpleNamespace(
                to_dict=lambda: {"id": file_id, "file_path": "a/b/c"}
            )

    class DummyApp(Application):
        def __init__(self):
            self.bot = DummyBot()

    queue = bot.query_queue
    # Clear the queue
    while not queue.empty():
        try:
            queue.get_nowait()
        except asyncio.QueueEmpty:
            break

    stop_event = asyncio.Event()

    async def stop_soon():
        await asyncio.sleep(0.01)
        stop_event.set()
        # Also put a dummy item so the queue.get() can complete
        await queue.put(
            types.SimpleNamespace(
                chat_id=1,
                message_id=1,
                file_id=None,
                message_entities=[],
                response=asyncio.Future()
            )
        )

    # Schedule stopping
    asyncio.create_task(stop_soon())
    # Run worker with a timeout to avoid infinite hang
    try:
        await asyncio.wait_for(bot.ptb_worker(DummyApp(), stop_event), timeout=0.2)
    except asyncio.TimeoutError:
        pytest.fail("ptb_worker did not finish in time")


def test_main_async_signature():
    # Ensure main_async is defined and is async
    assert hasattr(bot, "main_async")
    assert callable(bot.main_async)
    assert bot.main_async.__code__.co_flags & 0x80  # CO_COROUTINE
