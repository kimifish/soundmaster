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
    """Handler for DSP input change messages"""
    new_input: str = msg.payload.decode()
    EventBus().publish(Event(
        type=EventType.DSP_INPUT_MESSAGE,
        data={'new_input': new_input}
    ))


def on_dsp_input_pin_event(old_value, new_value):
    """Handler for DSP input pin state changes"""
    EventBus().publish(Event(EventType.DSP_INPUT_SWITCHED, {"new_input": new_value}))


def on_mute_message(msg: MQTTMessage) -> None:
    """Handler for mute state change messages"""
    new_state: str = msg.payload.decode().lower()
    mute_state = new_state == "true"
    # log.debug(f'{new_state=}, {mute_state=}')
    EventBus().publish(Event(
        type=EventType.MUTE_MESSAGE,
        data={'state': mute_state}
    ))


def on_master_volume_message(msg: MQTTMessage) -> None:
    """Handler for master volume change messages"""
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
    """Handler for channel volume change messages"""
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
        log.error(f"Error in channels volume message, all values should be int: {msg.payload}")
    except json.JSONDecodeError:
        log.error(f"Error decoding JSON in channels volume message: {msg.payload}")
    except Exception as e:
        log.error(f"Unexpected error: {e}")


def on_encoder_rotation(value: list):
    """Handler for encoder rotation events with acceleration"""
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
    """Handler for audio status change events"""
    EventBus().publish(Event(type=EventType.AUDIOSTATUS_CHANGED, data={'state': state}))


def on_encoder_press(value: list):
    """Handler for encoder button press events"""
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
    """Subscribe to MQTT topics and hardware events"""
    # MQTT subscriptions
    main_topic = cfg.mqtt.main_topic
    for topic_name, topic_path in cfg.mqtt.topics.set.items():
        full_topic = f"{main_topic}/{topic_path}"
        if topic_name == "active_input":
            cfg.mqtt.client.subscribe(full_topic, on_dsp_input_message)
        elif topic_name == "volume":
            cfg.mqtt.client.subscribe(full_topic, on_master_volume_message)
        elif topic_name == "volume_channels":
            cfg.mqtt.client.subscribe(full_topic, on_channel_volumes_message)
        elif topic_name == "mute":
            cfg.mqtt.client.subscribe(full_topic, on_mute_message)

    # Hardware subscriptions
    cfg.rt.encoder.subscribe(press_callback=on_encoder_press, rotation_callback=on_encoder_rotation)
    cfg.rt.dsp_monitor.subscribe(callback=on_dsp_input_pin_event)
    cfg.rt.audiostatus_monitor.subscribe(callback=on_audiostatus_changed)
    
