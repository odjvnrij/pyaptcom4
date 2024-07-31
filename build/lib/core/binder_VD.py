from .binder_base import BinderBase


class VD23(BinderBase):
    def __init__(self, ip: str, port: int = 502, timeout: int = 5):
        super().__init__(ip, port, timeout)

        self._wr_set_temp_addr = 0x4107
        self._wr_set_pressure_addr = 0x4110
        self._cur_temp_addr = 0x560a  # 22026
        self._cur_pressure_addr = 0x56dc  # 22236
        self._rd_set_temp_addr = 0x8c00  # 35840
        self._rd_set_pressure_addr = 0x8c02  # 35842
