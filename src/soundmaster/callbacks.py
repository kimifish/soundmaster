# pyright: basic
# pyright: reportAttributeAccessIssue=false

import logging
import time
import json
from paho.mqtt.client import MQTTMessage
from kimiconfig import Config
from event_bus import EventBus, Event, EventType

cfg = Config()
log = logging.getLogger(f'soundmaster.{__name__}')

last_rotation_event = [time.time(), 0]
last_button_event = [time.time(), 0]


def on_dsp_input_message(msg: MQTTMessage) -> None:
    """Обработчик сообщений о смене входа DSP"""
    new_input: str = msg.payload.decode()
    EventBus().publish(Event(
        type=EventType.DSP_INPUT_MESSAGE,
        data={'new_input': new_input}
    ))


def on_dsp_input_pin_event(old_value, new_value):
    EventBus().publish(Event(EventType.DSP_INPUT_SWITCHED, {"new_input": new_value}))


def on_mute_message(msg: MQTTMessage) -> None:
    """Обработчик сообщений о смене состояния mute"""
    new_state: str = msg.payload.decode().lower()
    mute_state = new_state == "true"
    # log.debug(f'{new_state=}, {mute_state=}')
    EventBus().publish(Event(
        type=EventType.MUTE_MESSAGE,
        data={'state': mute_state}
    ))


def on_master_volume_message(msg: MQTTMessage) -> None:
    """Обработчик сообщений о смене громкости"""
    try:
        new_volume = int(msg.payload.decode())
        new_volume = max(0, min(79, new_volume))
        EventBus().publish(Event(
            type=EventType.MASTER_VOLUME_MESSAGE,
            data={'new_volume': new_volume}
        ))
    except json.ValueError:
        log.error(f"Error in volume message, should be int: {msg.payload}")
    except Exception as e:
        log.error(f"Unexpected error: {e}")


def on_channel_volumes_message(msg: MQTTMessage) -> None:
    """Обработчик сообщений о смене громкости канала"""
    try:
        payload = msg.payload.decode()
        volume_data = json.loads(payload)
        
        if isinstance(volume_data, list):
                channel_volumes = [max(0, min(79, int(vol))) for vol in volume_data]
                EventBus().publish(Event(
                    type=EventType.CHANNEL_VOLUMES_MESSAGE,
                    data={'channels': channel_volumes}
                ))
    except json.ValueError:
        log.error(f"Error in cnannels volume message, all values should be int: {msg.payload}")
    except json.JSONDecodeError:
        log.error(f"Error decoding JSON in channels volume message: {msg.payload}")
    except Exception as e:
        log.error(f"Unexpected error: {e}")


def on_encoder_rotation(value: list):
    global last_rotation_event
    acceleration = [
        (10, 0.1),
        (5, 0.12),
        (4, 0.15),
        (3, 0.2),
        (2, 0.3),
    ]
    old_time, old_dir = last_rotation_event
    new_time, new_dir = value

    if old_dir * new_dir > 0:  # If direction is the same (by sign), counting acceleration
        delta = new_time - old_time
        for multiplier, d_time in acceleration:
            if delta < d_time:
                new_dir *= multiplier
                break

    EventBus().publish(Event(EventType.ENCODER_ROTATED, {"direction": new_dir}))
    last_rotation_event = value


def on_audiostatus_changed(state: str):
    EventBus().publish(Event(type=EventType.AUDIOSTATUS_CHANGED, data={'state': state}))


def on_encoder_press(value: list):
    global last_button_event
    old_time, old_event = last_button_event
    new_time, new_event = value
    # log.debug(f"{new_event=}")
    if old_event == new_event:
        log.warning("Same button event repeated.")
        return
    if not new_event:
        d_time = new_time - old_time
        if d_time < 1000:
            log.debug(f"Short press determined.")
            EventBus().publish(Event(EventType.ENCODER_PRESSED_SHORT, {"duration": "short"}))
        elif d_time < 10000:
            log.debug(f"Long press determined.")
            EventBus().publish(Event(EventType.ENCODER_PRESSED_LONG, {"duration": "long"}))
    last_button_event = value


def subscribe_callbacks():
    cfg.mqtt.client.subscribe("kimiHome/audio/soundmaster/Active_Input/set", on_dsp_input_message)
    cfg.mqtt.client.subscribe("kimiHome/audio/soundmaster/Volume/set", on_master_volume_message)
    cfg.mqtt.client.subscribe("kimiHome/audio/soundmaster/Volume/channels/set", on_channel_volumes_message)
    cfg.mqtt.client.subscribe("kimiHome/audio/soundmaster/Mute/set", on_mute_message)
    cfg.rt.encoder.subscribe(press_callback=on_encoder_press, rotation_callback=on_encoder_rotation)
    cfg.rt.dsp_monitor.subscribe(callback=on_dsp_input_pin_event)
    cfg.rt.audiostatus_monitor.subscribe(callback=on_audiostatus_changed)
    
