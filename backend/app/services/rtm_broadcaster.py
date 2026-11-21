import time
import logging
from typing import Dict, List, Any, Optional

logger = logging.getLogger(__name__)

class RTMBroadcaster:
    """
    Manages real-time event broadcasting to Frontend Command Center.
    Stores an in-memory ring-buffer of events per session for real-time retrieval and SSE.
    """
    def __init__(self):
        self._event_store: Dict[str, List[Dict[str, Any]]] = {}

    def broadcast_event(self, channel: str, event_type: str, payload: Dict[str, Any]):
        if channel not in self._event_store:
            self._event_store[channel] = []
        
        event_message = {
            "channel": channel,
            "event": event_type,
            "timestamp": int(time.time() * 1000),
            "data": payload
        }
        
        # Keep latest 100 events per channel
        self._event_store[channel].append(event_message)
        if len(self._event_store[channel]) > 100:
            self._event_store[channel].pop(0)

        logger.info(f"[RTM BROADCAST] Channel: {channel} | Event: {event_type} | Data: {payload}")

    def get_events_since(self, channel: str, last_timestamp: int = 0) -> List[Dict[str, Any]]:
        events = self._event_store.get(channel, [])
        if last_timestamp <= 0:
            return events
        return [e for e in events if e.get("timestamp", 0) > last_timestamp]

    def clear_channel(self, channel: str):
        if channel in self._event_store:
            del self._event_store[channel]

rtm_broadcaster = RTMBroadcaster()
