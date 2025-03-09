# pyright: basic
# pyright: reportAttributeAccessIssue=false

from dataclasses import dataclass
from functools import wraps
from typing import Any, Callable, Dict, Optional
import json
import logging
from contextlib import contextmanager

from kimiconfig import Config
from event_bus import EventBus, Event, EventType

cfg = Config()
log = logging.getLogger(f'soundmaster.{__name__}')

# Constants
VOLUME_MIN = 0
VOLUME_MAX = 79


@contextmanager
def safe_pt2258():
    """Context manager for safe PT2258 operations"""
    if hasattr(cfg, 'pt2258') and cfg.pt2258:  # Remove mute state check
        yield cfg.pt2258
    else:
        yield None


def publish_mqtt(topic_name: str) -> Callable:
    """Decorator for MQTT publishing with auto-formatting of topic"""
    def decorator(func: Callable) -> Callable:
        @wraps(func)
        def wrapper(*args, **kwargs):
            result = func(*args, **kwargs)
            topic_path = cfg.mqtt.topics.get(topic_name, topic_name)
            full_topic = f"{cfg.mqtt.main_topic}/{topic_path}"
            cfg.mqtt.client.publish(full_topic, result)
            return result
        return wrapper
    return decorator


def save_state(func: Callable) -> Callable:
    """Decorator to trigger state saving after handler execution"""
    @wraps(func)
    def wrapper(*args, **kwargs):
        result = func(*args, **kwargs)
        cfg.rt.settings_saver.handle()
        # EventBus().publish(Event(type=EventType.STATE_SAVED, data={}))
        return result
    return wrapper


def update_display(display_type: str) -> Callable:
    """Decorator for updating display after handler execution
    
    Args:
        display_type: Type of display update ('volume', 'input', or 'mute')
    """
    def decorator(func: Callable) -> Callable:
        @wraps(func)
        def wrapper(*args, **kwargs):
            result = func(*args, **kwargs)
            if hasattr(cfg.rt, 'display'):
                if display_type == 'volume':
                    cfg.rt.display.show_volume(cfg.rt.master_volume)
                elif display_type == 'input':
                    cfg.rt.display.show_input(cfg.rt.active_input)
                elif display_type == 'mute':
                    cfg.rt.display.show_mute(cfg.rt.mute_state)
            return result
        return wrapper
    return decorator


def clamp_volume(value: int) -> int:
    """Clamp volume value between MIN and MAX"""
    return max(VOLUME_MIN, min(VOLUME_MAX, value))


@publish_mqtt("mute")
def _act_mute() -> str:
    """Apply mute state to PT2258 and return MQTT payload"""
    with safe_pt2258() as pt2258:
        if pt2258:
            pt2258.mute(status=cfg.rt.mute_state)  # Apply mute state
            if not cfg.rt.mute_state:  # Only set volume if unmuting
                pt2258.master_volume(cfg.rt.master_volume)
    return str(cfg.rt.mute_state).lower()


@publish_mqtt("volume")
def _change_master_volume() -> int:
    """Apply master volume to PT2258 and return MQTT payload"""
    with safe_pt2258() as pt2258:
        if pt2258:
            pt2258.master_volume(cfg.rt.master_volume)
    return cfg.rt.master_volume


@publish_mqtt("volume_channels")
def _change_channel_volumes() -> str:
    """Apply channel volumes to PT2258 and return MQTT payload"""
    with safe_pt2258() as pt2258:
        if pt2258:
            for channel, volume in enumerate(cfg.rt.channel_volumes):
                pt2258.channel_volume(channel=channel, volume=volume)
    return json.dumps(cfg.rt.channel_volumes)


@save_state
@update_display('mute')
def handle_encoder_pressed(event: Event) -> None:
    """Toggle mute state on encoder press"""
    cfg.update('rt.mute_state', not cfg.rt.mute_state)
    _act_mute()
    log.info(f"Mute state toggled to: {'ON' if cfg.rt.mute_state else 'OFF'} via encoder")


@save_state
@update_display('volume')
def handle_encoder_rotated(event: Event) -> None:
    """Handle encoder rotation for volume control"""
    direction = event.data.get('direction', 0)
    new_volume = clamp_volume(cfg.rt.master_volume + direction)
    cfg.update('rt.master_volume', new_volume)
    _change_master_volume()
    log.info(f"Master volume adjusted to: {new_volume} via encoder")


@save_state
@update_display('volume')
def handle_master_volume_message(event: Event) -> None:
    """Handle MQTT master volume message"""
    new_volume = clamp_volume(event.data.get("new_volume", 0))
    cfg.update("rt.master_volume", new_volume)
    _change_master_volume()
    log.info(f"Master volume set to: {new_volume} via MQTT")


@save_state
def handle_channel_volumes_message(event: Event) -> None:
    """Handle MQTT channel volumes message"""
    channels = [clamp_volume(v) for v in event.data.get("channels", [])]
    cfg.update("rt.channel_volumes", channels)
    _change_channel_volumes()
    log.info(f"Channel volumes updated via MQTT: {channels}")


@save_state
@update_display('mute')
def handle_mute_message(event: Event) -> None:
    """Handle MQTT mute message"""
    cfg.update("rt.mute_state", event.data["state"])
    _act_mute()
    log.info(f"Mute state set to: {'ON' if cfg.rt.mute_state else 'OFF'} via MQTT")


@save_state
def handle_dsp_input_message(event: Event) -> None:
    """Handle DSP input change message"""
    cfg.rt.dsp_monitor.set_value(event.data.get("new_input", ""))


@save_state
@update_display('input')
@publish_mqtt("active_input")
def handle_dsp_input_switched(event: Event) -> str:
    """Handle DSP input switch event"""
    cfg.update("rt.active_input", event.data.get("new_input"))
    return cfg.rt.active_input


@publish_mqtt("audio_status")
def handle_audiostatus_changed(event: Event) -> str:
    """Handle audio status change event"""
    cfg.update("rt.state", event.data['state'])
    log.info(f'Audio output status: {event.data["state"]}')
    return cfg.rt.state


@update_display('input')
def handle_state_loaded(event: Event) -> None:
    """Handle state loaded event by applying all settings"""
    log.info("Applying loaded state")
    cfg.rt.dsp_monitor.set_value(cfg.rt.active_input)
    _change_channel_volumes()
    _change_master_volume()
    _act_mute()


def init_event_handlers() -> None:
    """Initialize all event handlers"""
    handlers = {
        EventType.ENCODER_PRESSED_SHORT: handle_encoder_pressed,
        EventType.ENCODER_ROTATED: handle_encoder_rotated,
        EventType.AUDIOSTATUS_CHANGED: handle_audiostatus_changed,
        EventType.MUTE_MESSAGE: handle_mute_message,
        EventType.DSP_INPUT_MESSAGE: handle_dsp_input_message,
        EventType.DSP_INPUT_SWITCHED: handle_dsp_input_switched,
        EventType.MASTER_VOLUME_MESSAGE: handle_master_volume_message,
        EventType.CHANNEL_VOLUMES_MESSAGE: handle_channel_volumes_message,
        EventType.STATE_LOADED: handle_state_loaded,
    }
    
    event_bus = EventBus()
    for event_type, handler in handlers.items():
        event_bus.subscribe(event_type, handler)

