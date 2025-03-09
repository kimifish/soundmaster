import time
from smbus2 import SMBus

class PT2258:
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

    def __init__(self, bus: SMBus, address: int = 0x88) -> None:
        """
        Initialize the PT2258 6-channel volume controller.

        :param bus: The SMBus object connected to the PT2258.
        :param address: The I2C address of the PT2258 (0x8C, 0x88, 0x84, or 0x80).
        :raises ValueError: If the bus object or address is not valid.
        """
        if bus is None:
            raise ValueError("The SMBus object 'bus' is missing!")
        if address not in [0x8C, 0x88, 0x84, 0x80]:
            raise ValueError(
                f"Invalid PT2258 device address {address}. It should be 0x8C, 0x88, 0x84, or 0x80."
            )

        self.__bus = bus

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