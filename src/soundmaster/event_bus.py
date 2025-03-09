# pyright: basic
# pyright: reportAttributeAccessIssue=false

import logging
from subprocess import call
from typing import Dict, List, Callable
# from dtypes import Event, EventType
from dataclasses import dataclass
from enum import Enum, auto
from typing import Dict, Any


log = logging.getLogger(f'soundmaster.{__name__}')


# log = logging.getLogger(f'soundmaster.{__name__}')


class EventType(Enum):
    ENCODER_PRESSED_SHORT = auto()
    ENCODER_PRESSED_LONG = auto()
    ENCODER_ROTATED = auto()
    AUDIOSTATUS_CHANGED = auto()
    STATE_LOADED = auto()
    STATE_SAVED = auto()
    PT2258_INIT = auto()
    DSP_INPUT_MESSAGE = auto()
    DSP_INPUT_SWITCHED = auto()
    MUTE_MESSAGE = auto()
    MASTER_VOLUME_MESSAGE = auto()
    CHANNEL_VOLUMES_MESSAGE = auto()


@dataclass
class Event:
    type: EventType
    data: Dict[str, Any]


class EventBus:
    _instance = None
    
    def __new__(cls):
        if cls._instance is None:
            cls._instance = super().__new__(cls)
            cls._instance._subscribers = {}
        return cls._instance

    def __init__(self):
        if not hasattr(self, '_subscribers'):
            self._subscribers: Dict[EventType, List[Callable]] = {
                event_type: [] for event_type in EventType
            }

    def subscribe(self, event_type: EventType, callback: list[Callable]|Callable) -> None:
        log.debug(f'Subscribe: {callback} to event {event_type}')
        if not isinstance(callback, list):
            callback = [callback]
        if event_type not in self._subscribers:
            self._subscribers[event_type] = []
        for c in callback:
            self._subscribers[event_type].append(c)

    def publish(self, event: Event) -> None:
        log.debug(f'New event: {event}')
        if event.type not in self._subscribers:
            log.debug(f'No subscribers for event type: {event.type}')
            return
        for callback in self._subscribers[event.type]:
            callback(event)
            
    def unsubscribe(self, event_type: EventType, callback: Callable[[Event], None]) -> None:
        if event_type in self._subscribers and callback in self._subscribers[event_type]:
            self._subscribers[event_type].remove(callback)
            log.debug(f'Unsubscribe: {callback} from event {event_type}')

