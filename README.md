# SoundMaster

An experimental project combining various hardware interfaces and technologies to create an audio control system. This project serves as a practical exploration of working with I2C devices, GPIO controls, MQTT communication, and display interfaces on single-board computers.

The system provides volume control through a PT2258 chip, with an OLED display for visual feedback and both physical (rotary encoder) and network (MQTT) controls. It's primarily developed as a learning exercise and technology demonstration.

## Features

- Volume control via PT2258 chip (driver based on [Vijay's implementation](https://github.com/zerovijay/PT2258))
- OLED display showing volume, input source, and mute status
- Rotary encoder with push button for control
- MQTT integration for remote control
- DSP input monitoring and switching
- State persistence between restarts

## Hardware Requirements

- Orange Pi or similar SBC with I2C support
- PT2258 volume control IC
- SSD1306 OLED display (128x32)
- Rotary encoder with push button
- DSP with input selection capability

## Installation

1. Clone the repository:
```bash
git clone https://github.com/yourusername/soundmaster.git
```

2. Install dependencies:
```bash
pip install -r requirements.txt
```

3. Configure your system:
   - Copy `config.yaml.example` to `config.yaml`
   - Adjust settings according to your hardware setup

## Configuration

Key configuration parameters in `config.yaml`:

```yaml
i2c:
  bus_number: 0
  pt2258:
    address: 0x44  # PT2258 I2C address
  display:
    address: 0x3C  # OLED display I2C address

mqtt:
  server: "localhost"
  port: 1883
  main_topic: "audio"

pins:
  encoder:
    left: 11    # GPIO pin for encoder left
    right: 12   # GPIO pin for encoder right
    key: 13     # GPIO pin for encoder button
```

## Usage

Run the application:
```bash
python -m soundmaster.main
```

### MQTT Topics

- `audio/Volume`: Get/set volume (0-79)
- `audio/Mute`: Get/set mute state (true/false)
- `audio/Input`: Get/set input source
```

## License

MIT License
