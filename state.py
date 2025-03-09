# pyright: basic
# pyright: reportAttributeAccessIssue=false

import threading
import json
import logging
from kimiconfig import Config
from event_bus import Event, EventType, EventBus

cfg = Config()
log = logging.getLogger(f'soundmaster.{__name__}')

class SettingsSaveHandler:
    def __init__(self):
        # Timer object to manage the delayed save
        self._timer = None
        # Lock to prevent race conditions
        self._lock = threading.Lock()
        # Delay in seconds
        self.DELAY = 10
        cfg.update("rt.settings_saver", self)

    # def handle(self, event: Event) -> None:
    def handle(self) -> None:
        """
        Handle incoming events and debounce the save_settings call.
        
        Args:
            event: The event object (unused in this case)
        """
        with self._lock:
            # Cancel existing timer if it exists
            if self._timer is not None:
                self._timer.cancel()
            
            # Create and start new timer
            self._timer = threading.Timer(self.DELAY, self._save_settings_thread)
            self._timer.start()

    def _save_settings_thread(self) -> None:
        """
        Thread function that calls save_settings after delay.
        Runs in a separate thread to avoid blocking the event bus.
        """
        try:
            self.save_settings()
        except Exception as e:
            log.error(f"Error saving settings: {e}")
        
        finally:
            with self._lock:
                # Clear timer reference after completion
                self._timer = None

    # Сохранение настроек в файл
    def save_settings(self):
        """Сохранение текущих настроек в state.json"""
        settings = {
            "master_volume": cfg.rt.master_volume,
            "channel_volumes": cfg.rt.channel_volumes,
            "mute_state": cfg.rt.mute_state,
            "active_input": cfg.rt.active_input
        }
        with open("state.json", "w") as f:
            json.dump(settings, f)
        EventBus().publish(Event(type=EventType.STATE_SAVED, data={}))
        log.debug("State saved.")


# Загрузка настроек из файла
def load_settings():
    """Загрузка настроек из state.json или использование значений по умолчанию"""
    try:
        with open("state.json", "r") as f:
            settings = json.load(f)
        log.debug("State loaded.")
    except Exception as e:
        log.warning(f"Ошибка загрузки настроек: {e}, используются значения по умолчанию")
        settings = {}

    cfg.update('rt.master_volume', settings.get("master_volume", 50))
    cfg.update('rt.channel_volumes', settings.get("channel_volumes", [50] * 6))
    cfg.update('rt.mute_state', settings.get("mute_state", False))
    cfg.update('rt.active_input', settings.get("active_input", "OPi"))

    EventBus().publish(Event(type=EventType.STATE_LOADED, data={}))

