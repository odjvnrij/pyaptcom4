from enum import IntEnum, Enum


class ModBusMsgType(IntEnum):
    ReadHoldReg = 0x03
    ReadWrReg = 0x04
    WriteMultiReg = 0x10


class ModBusHeader:
    def __init__(self, byte: bytes):
        self.trans_id = int.from_bytes(byte[0:2], byteorder='big')
        self.rest_len = int.from_bytes(byte[4:6], byteorder="big")
        self.len = len(byte)
        self.body_len = self.rest_len - 1
        self.unit_id = byte[6]
        self.byte = byte


class ModBusBody:
    def __init__(self, byte: bytes):
        self.msg_type = ModBusMsgType(byte[0])
        self.byte = byte
