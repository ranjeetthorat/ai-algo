"""System-level events not tied to a user API call.

Currently the broker-feed connection status, published by the order-update
adapter lifecycle (websocket_proxy/order_adapter.py) so the UI can raise a
connection alarm when the broker link drops. The order-update WebSocket and the
market-data feed die together on a network loss, so this one in-process signal
is a faithful "broker link is down" indicator - and the only one available in
the desktop case, where the browser still reaches the local server fine.
"""

from dataclasses import dataclass

from utils.event_bus import Event


@dataclass
class BrokerFeedStatusEvent(Event):
    """The broker connection changed state.

    status:
      - "connected"    the broker link is up (a successful connect/reconnect)
      - "reconnecting" the link dropped and the adapter is retrying
      - "down"         the link cannot recover on its own (token rejected);
                       a broker login is required
    """

    topic: str = "broker.feed_status"
    status: str = "connected"
    broker: str = ""
    user_id: str = ""
    attempt: int = 0
    message: str = ""
