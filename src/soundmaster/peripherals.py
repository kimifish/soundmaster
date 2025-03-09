# pyright: basic
# pyright: reportAttributeAccessIssue=false

import logging
import threading
import time
from typing import Callable
from smbus2 import SMBus
import OPi.GPIO as GPIO
from kimiconfig import Config
from event_bus import EventBus, Event, EventType
from luma.core.interface.serial import i2c
from luma.core.render import canvas
from luma.oled.device import ssd1306
from PIL import ImageFont
import queue
from queue import Queue

cfg = Config()
log = logging.getLogger(f'soundmaster.{__name__}')

GPIO.setmode(GPIO.BOARD)
GPIO.setwarnings(False)

def GPIO_cleanup():
    GPIO.cleanup()

class PT2258:
    """
    PT2258 6-channel electronic volume controller IC driver.
    
    Based on the original implementation by Vijay (github.com/zerovijay/PT2258).
    Thanks to Vijay for the initial implementation and reverse engineering of the PT2258 protocol.
    
    This class provides an interface to control the PT2258 volume controller IC via I2C,
    supporting master volume, individual channel volume, and mute functionality.
    """
    # Constants for clear registers
    __CLEAR_REGISTER = 0xC0

    # Constants for master volume registers
    __MUTE_REGISTER = 0xF8
    __MASTER_VOLUME_10DB = 0xD0
    __MASTER_VOLUME_1DB = 0xE0

    # Constants for channel registers 10dB
    __C1_10DB = 0x80
    __C2_10DB = 0x40
    __C3_10DB = 0x00
    __C4_10DB = 0x20
    __C5_10DB = 0x60
    __C6_10DB = 0xA0

    # Constants for channel registers 1dB
    __C1_1DB = 0x90
    __C2_1DB = 0x50
    __C3_1DB = 0x10
    __C4_1DB = 0x30
    __C5_1DB = 0x70
    __C6_1DB = 0xB0

    def __init__(self, bus: int, address: int = 0x88) -> None:
        """
        Initialize the PT2258 6-channel volume controller.

        :param bus: The SMBus object connected to the PT2258.
        :param address: The I2C address of the PT2258 (0x8C, 0x88, 0x84, or 0x80).
        :raises ValueError: If the bus object or address is not valid.
        """

        self.__bus = SMBus(bus)

        if self.__bus is None:
            raise ValueError("The SMBus object 'bus' is missing!")
        if address not in [0x8C, 0x88, 0x84, 0x80]:
            raise ValueError(
                f"Invalid PT2258 device address {address}. It should be 0x8C, 0x88, 0x84, or 0x80."
            )

        # PT2258 only accepts 7-bit addresses.
        self.__PT2258_ADDR = address >> 1

        self.__CHANNEL_REGISTERS = (
            (self.__C1_10DB, self.__C1_1DB),  # Channel 1 (10dB, 1dB)
            (self.__C2_10DB, self.__C2_1DB),  # Channel 2 (10dB, 1dB)
            (self.__C3_10DB, self.__C3_1DB),  # Channel 3 (10dB, 1dB)
            (self.__C4_10DB, self.__C4_1DB),  # Channel 4 (10dB, 1dB)
            (self.__C5_10DB, self.__C5_1DB),  # Channel 5 (10dB, 1dB)
            (self.__C6_10DB, self.__C6_1DB),  # Channel 6 (10dB, 1dB)
        )

        self.__last_ack = 0

        # Initialize the PT2258
        self.__last_ack = self.__initialize_pt2258()
        if self.__last_ack != 1:
            raise RuntimeError(
                "Failed to initialize PT2258! Please double check the I2C connection."
            )

    def __write_pt2258(self, write_data: int) -> int:
        """
        Write an instruction to the PT2258 via I2C.

        :param write_data: The instruction data to be written to PT2258.
        :return: Acknowledgment (1 if successful)
        """
        try:
            self.__bus.write_byte(self.__PT2258_ADDR, write_data)
            ack = 1  # In smbus2, a successful write does not return an acknowledgment value.
        except OSError as error:
            # Check for error number 5 (I/O error) or other errors.
            if error.errno == 5:
                raise RuntimeError("Communication error with the PT2258 during the operation!")
            else:
                raise RuntimeError(f"Communication error with the PT2258! Error message: {error}")
        return ack

    def __initialize_pt2258(self) -> int:
        """
        Initialize the PT2258 6-channel volume controller IC.

        Wait for at least 300ms for stability after power-on and then clear the register.

        :return: Acknowledgment (1 if successful)
        """
        # Wait for at least 300ms for stability.
        time.sleep(0.3)

        # Check if the PT2258 device is present by trying to read a byte.
        # try:
        #     self.__bus.read_byte(self.__PT2258_ADDR)
        # except OSError:
        #     raise OSError("PT2258 not found on the I2C bus.")

        # Clear the specified register to initialize the PT2258.
        self.__last_ack = self.__write_pt2258(self.__CLEAR_REGISTER)
        return self.__last_ack

    def master_volume(self, volume: int = 0) -> int:
        """
        Set the master volume.

        :param volume: The desired master volume level (0 to 79).
        :return: Acknowledgment (1 if successful)
        """
        if not 0 <= volume <= 79:
            raise ValueError("The master volume should be within the range of 0 to 79.")

        # Calculate attenuation values for 10dB and 1dB settings.
        att_10db, att_1db = divmod(79 - volume, 10)

        # Send attenuation settings to the PT2258.
        self.__last_ack = self.__write_pt2258(self.__MASTER_VOLUME_10DB | att_10db)
        if self.__last_ack:
            self.__last_ack = self.__write_pt2258(self.__MASTER_VOLUME_1DB | att_1db)
        return self.__last_ack

    def channel_volume(self, channel: int, volume: int = 0) -> int:
        """
        Set the volume level for a specific channel.

        :param channel: The index of the channel (0 to 5).
        :param volume: The desired volume level for the channel (0 to 79).
        :return: Acknowledgment (1 if successful)
        """
        if not 0 <= volume <= 79:
            raise ValueError("The volume should be within the range of 0 to 79.")
        if not 0 <= channel <= 5:
            raise ValueError("Invalid channel index. Channels should be within the range of 0 to 5.")

        # Get the 10dB and 1dB channel registers for the specified channel.
        channel_10db, channel_1db = self.__CHANNEL_REGISTERS[channel]

        # Calculate attenuation values for 10dB and 1dB settings.
        att_10db, att_1db = divmod(79 - volume, 10)

        # Send attenuation settings to the PT2258.
        self.__last_ack = self.__write_pt2258(channel_10db | att_10db)
        if self.__last_ack:
            self.__last_ack = self.__write_pt2258(channel_1db | att_1db)
        return self.__last_ack

    def mute(self, status: bool = False) -> int:
        """
        Enable or disable the mute functionality.

        :param status: True to mute, False to unmute.
        :return: Acknowledgment (1 if successful)
        """
        if not isinstance(status, bool):
            raise ValueError("Invalid mute status value. It should be a boolean (True or False).")

        self.__last_ack = self.__write_pt2258(self.__MUTE_REGISTER | status)
        return self.__last_ack


class AudioCardStatusMonitor(threading.Thread):
    """
    Thread that periodically reads /proc/asound/card0/pcm0p/sub0/status
    and updates audio_status variable ('off' if 'closed\n', otherwise 'on').
    """
    def __init__(self, interval=1.0, filepath=None):
        """
        callback: function to call when status changes
        interval: polling period (seconds)
        """
        super().__init__()
        self.interval = interval
        self.filepath = filepath
        self.running = True
        self.current_status = None
        self.callbacks = list()

    def subscribe(self, callback: Callable|None = None):
        if callback is not None:
            self.callbacks.append(callback)

    def run(self):
        log.debug(f"[AudioCardStatusMonitor] Monitoring started: {self.filepath}")
        if self.filepath is None:
            log.warning(f"File for detecting audiocard status isn't given. This functionality is canceled.")
            return
        while self.running:
            status_text = ""
            try:
                with open(self.filepath, "r") as f:
                    status_text = f.read()
            except Exception as e:
                log.debug(f"Error while detecting audiocard status: {e}")
            
            new_status = "off" if status_text == "closed\n" else "on"
            if new_status != self.current_status:
                self.current_status = new_status
                for callback in self.callbacks:
                    callback(new_status)
            
            time.sleep(self.interval)

    def stop(self):
        self.running = False


class Encoder:

    def __init__(self, left_pin, right_pin, button_pin, rotation_callback=None, press_callback=None):
        self.left_pin = left_pin
        self.right_pin = right_pin
        self.button = button_pin
        self.direction = 0
        self.state = 0
        self.button_state = 0
        self.rotation_callback = rotation_callback
        self.press_callback = press_callback

        GPIO.setup(self.left_pin, GPIO.IN) #, pull_up_down=GPIO.PUD_UP)
        GPIO.setup(self.right_pin, GPIO.IN) #, pull_up_down=GPIO.PUD_UP)
        GPIO.setup(self.button, GPIO.IN)

        GPIO.add_event_detect(self.left_pin, GPIO.BOTH, callback=self.rotation_event, bouncetime=20)
        GPIO.add_event_detect(self.right_pin, GPIO.BOTH, callback=self.rotation_event, bouncetime=20)
        GPIO.add_event_detect(self.button, GPIO.BOTH, callback=self.button_event, bouncetime=20)

    def subscribe(self, press_callback=None, rotation_callback=None):
        if press_callback is not None:
            self.press_callback = press_callback
        if rotation_callback is not None:
            self.rotation_callback= rotation_callback

    def button_event(self, channel):
        new_state = bool(not GPIO.input(self.button))
        if new_state == self.button_state:
            return
        if self.press_callback is not None:
            self.press_callback([time.time(), new_state])
        self.button_state = new_state

    def rotation_event(self, channel):
        p1 = GPIO.input(self.left_pin)
        p2 = GPIO.input(self.right_pin)
        new_state = (p1 << 1) + p2

        # Bouncing?
        if new_state == self.state:
            return

        # First event gives us rotation direction. Saving it.
        if self.state == 0:
            self.direction = p1 - p2

        if new_state == 3 and self.direction in (-1, 1) and self.rotation_callback is not None:
            self.rotation_callback( [time.time(), self.direction] )
            self.direction = 0

        if new_state == 0:
            self.direction = 0

        self.state = new_state


class DSPInputMonitor:
    def __init__(self, pin1, pin2, pin3, switch_pin):
        self.pin1 = pin1
        self.pin2 = pin2
        self.pin3 = pin3
        self.switch_pin = switch_pin  # Pin for switching emulation
        self.value_list = ["OPi", "Opt1", "Opt2", "AUX"]
        self.stop_event = threading.Event()
        self.callback = None

        # Pin configuration
        GPIO.setmode(GPIO.BOARD)
        GPIO.setup(self.pin1, GPIO.IN, pull_up_down=GPIO.PUD_DOWN)
        GPIO.setup(self.pin2, GPIO.IN, pull_up_down=GPIO.PUD_DOWN)
        GPIO.setup(self.pin3, GPIO.IN, pull_up_down=GPIO.PUD_DOWN)
        GPIO.setup(self.switch_pin, GPIO.OUT)  # Fourth pin as output
        GPIO.output(self.switch_pin, GPIO.LOW)  # Initially set to low level

        # Determine initial value
        self.current_value = self._determine_value(
            GPIO.input(self.pin1), GPIO.input(self.pin2), GPIO.input(self.pin3)
        )

        # Add event handlers for input pins
        GPIO.add_event_detect(self.pin1, GPIO.BOTH, callback=self._pin_event)
        GPIO.add_event_detect(self.pin2, GPIO.BOTH, callback=self._pin_event)
        GPIO.add_event_detect(self.pin3, GPIO.BOTH, callback=self._pin_event)

    def _determine_value(self, pin1_state, pin2_state, pin3_state):
        """Determine current value based on pin states"""
        if pin1_state and not pin2_state and not pin3_state:
            return "Opt1"
        elif not pin1_state and pin2_state and not pin3_state:
            return "Opt2"
        elif not pin1_state and not pin2_state and pin3_state:
            return "AUX"
        elif not pin1_state and not pin2_state and not pin3_state:
            return "OPi"
        else:
            return self.current_value

    def _pin_event(self, channel):
        """Handle changes on input pins"""
        pin1_state = GPIO.input(self.pin1)
        pin2_state = GPIO.input(self.pin2)
        pin3_state = GPIO.input(self.pin3)
        new_value = self._determine_value(pin1_state, pin2_state, pin3_state)
        if new_value != self.current_value:
            old_value, self.current_value = self.current_value, new_value
            if self.callback is not None:
                self.callback(old_value, new_value)

    def _emulate_switch(self):
        """Emulate button press: 100ms pulse"""
        GPIO.output(self.switch_pin, GPIO.HIGH)
        time.sleep(0.15)  # 100 ms
        GPIO.output(self.switch_pin, GPIO.LOW)

    def subscribe(self, callback = None):
        if isinstance(callback, Callable):
            self.callback = callback

    def set_value(self, target_value):
        """Set desired value using pulses"""
        if target_value not in self.value_list:
            log.warning(f"Unsupported value: {target_value}")
            return

        max_attempts = 10  # Limit on number of attempts
        attempts = 0

        while self.current_value != target_value and attempts < max_attempts:
            self._emulate_switch()
            time.sleep(0.5)  # Wait for pin state update
            attempts += 1

        if self.current_value == target_value:
            log.info(f"DSP Input switched to {target_value}.")
        else:
            log.error(f"Changing DSP input to {target_value} failed after 10 attempts.")

    def run(self):
        """Start thread (not currently used)"""
        pass

    def stop(self):
        """Stop and clean up"""
        self.stop_event.set()
        GPIO.cleanup()


class Display:
    def __init__(self):
        self.device = None
        self.display_timer = None
        self.current_text = ""
        self.is_muted = False
        self.update_queue = Queue()
        self.update_thread = threading.Thread(target=self._update_loop, daemon=True)
        self.running = True
        self._initialize()
        self.update_thread.start()

    def _initialize(self):
        """Initialize the OLED display"""
        try:
            serial = i2c(port=cfg.i2c.bus_number, address=cfg.i2c.display.address)
            self.device = ssd1306(serial, width=128, height=32)
            self.device.contrast(255)
            log.info("Display initialized successfully")
        except Exception as e:
            log.error(f"Display initialization failed: {e}")
            self.device = None

    def _update_loop(self):
        """Main display update loop running in separate thread"""
        while self.running:
            try:
                # Get next update request with timeout
                update_func, args = self.update_queue.get(timeout=0.5)
                update_func(*args)
                self.update_queue.task_done()
            except queue.Empty: 
                continue
            except Exception as e:
                log.error(f"Display update error: {e}")

    def _clear_display_timer(self):
        """Clear existing display timer if any"""
        if self.display_timer and self.display_timer.is_alive():
            self.display_timer.cancel()

    def _schedule_clear(self):
        """Schedule display clearing after 7 seconds"""
        self._clear_display_timer()
        if not self.is_muted:  # Don't schedule clear if muted
            self.display_timer = threading.Timer(7.0, self.clear)
            self.display_timer.start()

    def _show_text_impl(self, text: str, persistent: bool = False):
        """Internal implementation of text display"""
        if not self.device:
            return

        self.current_text = text
        try:
            with canvas(self.device) as draw:
                try:
                    font = ImageFont.truetype(cfg.display.font, cfg.display.size)
                except:
                    font = ImageFont.load_default()
                
                # Get text dimensions
                bbox = draw.textbbox((0, 0), text, font=font)
                text_width = bbox[2] - bbox[0]
                text_height = bbox[3] - bbox[1]
                
                # Calculate center position
                x = (self.device.width - text_width) // 2
                y = (self.device.height - text_height) // 2 - 6
                
                # Draw centered text
                draw.text((x, y), text, fill="white", font=font)
            
            if not persistent:
                self._schedule_clear()
                
        except Exception as e:
            log.error(f"Error displaying text: {e}")

    def show_text(self, text: str, persistent: bool = False):
        """Queue text display update"""
        self.update_queue.put((self._show_text_impl, (text, persistent)))

    def clear(self):
        """Queue display clear"""
        if self.device and not self.is_muted:
            self.update_queue.put((self.device.clear, ()))
            self.current_text = ""

    def show_volume(self, volume: int):
        """Queue volume display update"""
        if volume == 0:
            display_text = "Min"
        elif volume == 79:
            display_text = "Max"
        else:
            display_text = f"{volume}"
        self.show_text(display_text)

    def show_input(self, input_name: str):
        """Queue input name display update"""
        self.show_text(input_name)

    def show_mute(self, is_muted: bool):
        """Queue mute state display update"""
        self.is_muted = is_muted
        if is_muted:
            self.show_text("Muted", persistent=True)
        else:
            self.clear()

    def stop(self):
        """Stop the display update thread"""
        self.running = False
        self.update_thread.join()


def init_encoder():
    cfg.update(
        "rt.encoder", 
        Encoder(
            left_pin=cfg.pins.encoder.left,
            right_pin=cfg.pins.encoder.right,
            button_pin=cfg.pins.encoder.key,
        )
    )
    log.info("Encoder initialized.")

def init_dsp_monitor():
    cfg.update(
        "rt.dsp_monitor",
        DSPInputMonitor(
            switch_pin=cfg.pins.dsp.button,
            pin1=cfg.pins.dsp.opt,
            pin2=cfg.pins.dsp.aux,
            pin3=cfg.pins.dsp.tv,
        )
    )
    log.info("DSP monitor initialized.")

def init_PT2258():
    try:
        cfg.update("pt2258", PT2258(bus=cfg.i2c.bus_number, address=cfg.i2c.pt2258.address))
        EventBus().publish(Event(type=EventType.PT2258_INIT, data={}))
    except ValueError as e:
        log.error(e)
    log.info("PT2258 volume manager initialized.")

def init_audiostatus_monitor():
    try:
        cfg.update(
            "rt.audiostatus_monitor",
            AudioCardStatusMonitor(interval=1.0, filepath=cfg.soundcard_status_file)
        )
        cfg.rt.audiostatus_monitor.start()
    except Exception as e:
            log.error(e)
    log.info("Audiocard status monitor initialized.")

def init_display():
    """Initialize display"""
    try:
        cfg.update("rt.display", Display())
        log.info("Display initialized.")
    except Exception as e:
        log.error(f"Display initialization failed: {e}")
