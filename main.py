# pyright: basic
# pyright: reportAttributeAccessIssue=false

import argparse
import logging
import sys
import time
import os
from typing import Dict, List, Optional, Any
from rich.traceback import install as install_rich_traceback
from rich.console import Console
from rich.logging import RichHandler

from kimiconfig import Config
cfg = Config(use_dataclasses=True)

from kiMQTT import MQTT
from kimiUtils.killer import GracefulKiller
import peripherals
import callbacks
import state
import handlers


DEFAULT_CONFIG_FILE = './config.yaml'


# Logging setup
logging.basicConfig(
    level=logging.NOTSET,
    format="%(message)s",
    datefmt="%X",
    handlers=[RichHandler(console=Console(), markup=True)],
)
parent_logger = logging.getLogger("soundmaster")

for logger_name in [
    "kiMQTT",
    "paho-mqtt",
]:
    logging.getLogger(logger_name).setLevel(logging.WARNING)

log = logging.getLogger(f'soundmaster.{__name__}')
install_rich_traceback(show_locals=True)

killer = GracefulKiller()


def _parse_args() -> tuple[argparse.Namespace, List[str]]:
    parser = argparse.ArgumentParser(
        prog='soundmaster',
        description='Audio control system for PT2258-based volume control')
    
    parser.add_argument(
        '-c', '--config',
        dest='config_file',
        default=DEFAULT_CONFIG_FILE,
        help=f'Path to configuration file (default: {DEFAULT_CONFIG_FILE})'
    )
    
    parser.add_argument(
        '-v', '--verbose',
        action='store_true',
        help='Enable verbose logging'
    )
    
    args, unknown = parser.parse_known_args()
    
    # Validate config file exists
    if not os.path.exists(args.config_file):
        parser.error(f"Config file not found: {args.config_file}")
        
    return args, unknown


def _init_config(config_file: str, unknown_args: List[str]):
    cfg.load_files([config_file,])
    cfg.load_args(unknown_args)


def _init_logging(verbose):
    cfg.update("logging.level", "DEBUG" if verbose else cfg.logging.level)
    handler = RichHandler(rich_tracebacks=cfg.logging.rich_tracebacks,
                          level=cfg.logging.level,
                          show_time=cfg.logging.show_time,
                          show_path=cfg.logging.show_path,
                          markup=cfg.logging.markup,
                          )
    handler.setFormatter(logging.Formatter(fmt=cfg.logging.format,
                                           datefmt=cfg.logging.date_format,
                                           )
                        )
    log.addHandler(handler)
    log.setLevel(cfg.logging.level)


def _init_mqtt():
    mqtt = MQTT(
        connect_on_init=False, 
        host=cfg.mqtt.server, 
        port=cfg.mqtt.port, 
        client_id=f"{os.uname()[1]}-0",
        )
    cfg.update('mqtt.client', mqtt)
    return mqtt


def _get_nested_attr(obj, path: str) -> Any:
    """
    Recursively get nested attribute from object using dot notation.
    
    Args:
        obj: Object to traverse
        path: Dot-separated path to attribute (e.g. 'mqtt.server')
        
    Returns:
        Attribute value if found
        
    Raises:
        AttributeError: If attribute doesn't exist
    """
    try:
        if '.' not in path:
            return getattr(obj, path)
        first, rest = path.split('.', 1)
        return _get_nested_attr(getattr(obj, first), rest)
    except AttributeError:
        raise AttributeError(f"Missing attribute: {path}")

def _validate_config():
    """Validate required configuration parameters"""
    required = {
        'mqtt.server': 'MQTT server address',
        'mqtt.port': 'MQTT port',
        'pins.encoder.key': 'Encoder key pin',
        'pins.encoder.left': 'Encoder left pin',
        'pins.encoder.right': 'Encoder right pin',
        'pins.dsp.opt': 'DSP optical input pin',
        'pins.dsp.aux': 'DSP aux input pin',
        'pins.dsp.tv': 'DSP TV input pin',
        'pins.dsp.button': 'DSP button pin',
        'pins.dsp.dsp_button': 'DSP control button pin',
        'i2c.bus_number': 'I2C bus number',
        'i2c.pt2258.address': 'PT2258 I2C address',
        'i2c.display.address': 'Display I2C address',
        'display.font': 'Display font',
        'display.size': 'Display font size',

    }
    
    missing = []
    for path, description in required.items():
        try:
            _get_nested_attr(cfg, path)
        except AttributeError:
            missing.append(f"{description} ({path})")
            
    if missing:
        raise ValueError(f"Missing required configuration: {', '.join(missing)}")


def main() -> int:
    try:
        log.info("Starting...")
        arguments, unknown_args = _parse_args()
        _init_config(arguments.config_file, unknown_args)
        _init_logging(arguments.verbose)
        _init_mqtt()
        _validate_config()
        
        # Initialize components with error handling
        components = [
            ('PT2258', peripherals.init_PT2258),
            ('Display', peripherals.init_display),
            ('Encoder', peripherals.init_encoder),
            ('DSP Monitor', peripherals.init_dsp_monitor),
            ('Audio Status Monitor', peripherals.init_audiostatus_monitor),
            ('Event Handlers', handlers.init_event_handlers),
            ('MQTT Callbacks', callbacks.subscribe_callbacks),
        ]
        
        for name, init_func in components:
            try:
                init_func()
            except Exception as e:
                log.error(f"Failed to initialize {name}: {e}")
                return 1
        
        try:
            cfg.mqtt.client.connect()
        except Exception as e:
            log.error(f"Failed to connect to MQTT broker: {e}")
            return 1

        # Load state and initialize state saver
        state.load_settings()
        state.SettingsSaveHandler()

        # Add graceful shutdown handlers
        killer.add_target([
            cfg.rt.audiostatus_monitor.stop,
            cfg.rt.display.stop,
            cfg.mqtt.client.loop_stop,
            peripherals.GPIO_cleanup,
        ])

        if cfg.logging.level == 'DEBUG':
            cfg.print_config()

        while not killer.kill_now:
            time.sleep(.5)
            
        return 0
        
    except Exception as e:
        log.error(f"Fatal error: {e}")
        return 1
    finally:
        # Ensure cleanup happens even on error
        try:
            peripherals.GPIO_cleanup()
        except:
            pass


if __name__ == "__main__":
    sys.exit(main())
