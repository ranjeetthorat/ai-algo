"""Broker-feed connection status: the signal behind the UI connection alarm.

Covers the publish path from the order-update adapter and the socketio
subscriber that emits it and caches the last value for late-joining clients.
"""

import threading

import pytest


def test_event_defaults():
    from events import BrokerFeedStatusEvent

    e = BrokerFeedStatusEvent(status="down", broker="shoonya", user_id="u1")
    assert e.topic == "broker.feed_status"
    assert e.status == "down"
    assert e.broker == "shoonya"
    assert e.attempt == 0


def test_adapter_reports_status_onto_bus():
    """_report_feed_status publishes a BrokerFeedStatusEvent with the adapter's
    identity, on the broker.feed_status topic, via the shared event bus."""
    from utils.event_bus import bus
    from websocket_proxy.order_adapter import BaseOrderUpdateAdapter

    received = []
    done = threading.Event()

    def capture(event):
        received.append(event)
        done.set()

    bus.subscribe("broker.feed_status", capture, "test:capture")
    try:
        # Call the real method with a lightweight stand-in for self, so no
        # abstract-method implementation is needed.
        class _FakeLogger:
            def debug(self, *a, **k):
                pass

        fake = type("F", (), {})()
        fake.broker_name = "shoonya"
        fake.user_id = "ranjeet"
        fake.logger = _FakeLogger()

        BaseOrderUpdateAdapter._report_feed_status(
            fake, "reconnecting", attempt=3, message="hi"
        )
        assert done.wait(timeout=5), "event was never delivered"
    finally:
        bus.unsubscribe("broker.feed_status", capture)

    evt = received[0]
    assert evt.topic == "broker.feed_status"
    assert evt.status == "reconnecting"
    assert evt.broker == "shoonya"
    assert evt.user_id == "ranjeet"
    assert evt.attempt == 3


class _FakeSocketIO:
    def __init__(self):
        self.emits = []

    def emit(self, event, payload=None):
        self.emits.append((event, payload))

    def on_event(self, name, handler):
        self.handler = handler


@pytest.fixture
def sub(monkeypatch):
    from subscribers import socketio_subscriber

    fake = _FakeSocketIO()
    monkeypatch.setattr(socketio_subscriber, "socketio", fake)
    # Isolate the module-level cache between tests.
    monkeypatch.setattr(socketio_subscriber, "_last_feed_status", {})
    return socketio_subscriber, fake


def test_subscriber_emits_and_caches(sub):
    socketio_subscriber, fake = sub
    evt = type("E", (), {})()
    evt.status, evt.broker, evt.user_id, evt.attempt, evt.message = (
        "down",
        "shoonya",
        "u1",
        0,
        "Broker session expired.",
    )
    socketio_subscriber.on_broker_feed_status(evt)

    assert fake.emits == [
        (
            "broker_feed_status",
            {"status": "down", "broker": "shoonya", "attempt": 0, "message": "Broker session expired."},
        )
    ]
    assert ("shoonya", "u1") in socketio_subscriber._last_feed_status


def test_query_resends_last_status(sub):
    socketio_subscriber, fake = sub
    evt = type("E", (), {})()
    evt.status, evt.broker, evt.user_id, evt.attempt, evt.message = (
        "reconnecting",
        "shoonya",
        "u1",
        2,
        "",
    )
    socketio_subscriber.on_broker_feed_status(evt)
    fake.emits.clear()

    # A client connecting during the outage asks for current status.
    socketio_subscriber.on_broker_feed_status_query()
    assert fake.emits == [
        ("broker_feed_status", {"status": "reconnecting", "broker": "shoonya", "attempt": 2, "message": ""}),
    ]


def test_query_silent_when_nothing_known(sub):
    socketio_subscriber, fake = sub
    socketio_subscriber.on_broker_feed_status_query()
    assert fake.emits == []
