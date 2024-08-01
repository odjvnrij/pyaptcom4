import logging
import queue
import socket
import threading
import traceback
import logging
import struct
import time
from queue import Queue

from . import tools
from .base import *

logger = logging.getLogger("BINDER")

def get_float_from_byte(byte: bytes) -> float:
    return struct.unpack('f', bytearray((byte[1], byte[0], byte[3], byte[2])))[0]


def get_byte_from_float(f: float) -> bytes:
    byte = struct.pack('f', f)
    return bytearray((byte[1], byte[0], byte[3], byte[2]))


class BinderBase:
    """
    BINDER 设备的基类
    """

    def __init__(self, server_ip: str, server_port: int = 502, timeout: int = 5):
        self.server_ip = server_ip
        self.server_port = int(server_port)
        self.server_addr = (self.server_ip, self.server_port)
        self.socket = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        self._timeout = int(timeout) if timeout else 5
        self._is_open = False
        self._recv_th = None

        self._monitor_th = None
        self._is_monitor_open = False
        self._is_force_stable = False
        self._is_monitor_temp = False
        self._is_monitor_pressure = False
        self.latest_temp = 0
        self.latest_pressure = 0
        self.latest_temp_setpoint = 0
        self.latest_pressure_setpoint = 0
        self._history_temp = []
        self._history_pressure = []
        self._monitor_interval = 10  # 1 min -> 6x query, 60x query -> 10 min
        self._stable_threshold_minute = 30
        self._stable_threshold = 180
        self._stable_threshold_temp = 0.2
        self._stable_threshold_pressure = 20
        self._temp_stable_event = threading.Event()
        self._pressure_stable_event = threading.Event()

        self._cur_trans_id = 0
        self._cur_resp_event = threading.Event()
        self._cur_resp_header = None
        self._cur_resp_body = None

        self._wr_temp_setpoint_addr = 0
        self._wr_pressure_setpoint_addr = 0
        self._cur_temp_addr = 0  # 22026
        self._cur_pressure_addr = 0  # 22236
        self._rd_temp_setpoint_addr = 0  # 35840
        self._rd_pressure_setpoint_addr = 0  # 35842

        self._temp_setpoint = 0
        self._pressure_setpoint = 0
        self._cur_temp = 0
        self._cur_pressure = 0

    @property
    def is_open(self) -> bool:
        return self._is_open

    @property
    def timeout(self):
        return self._timeout

    @timeout.setter
    def timeout(self, timeout: int):
        """
        tcp timeout
        :param timeout:
        :return:
        """
        self._timeout = int(timeout)
        if self.socket:
            self.socket.settimeout(self._timeout)

    @property
    def monitor_interval(self):
        """
        sec interval to query in monitor
        :return:
        """
        return self._monitor_interval

    @monitor_interval.setter
    def monitor_interval(self, interval: int):
        self._monitor_interval = int(interval)
        if not self._monitor_interval:
            raise ValueError

        self._stable_threshold = self._stable_threshold_minute * 60 / self._monitor_interval

    @property
    def stable_threshold_minute(self):
        return self._stable_threshold_minute

    @stable_threshold_minute.setter
    def stable_threshold_minute(self, threshold: int):
        self._stable_threshold_minute = int(threshold)
        if not self._stable_threshold_minute:
            raise ValueError

        self._stable_threshold = self._stable_threshold_minute * 60 / self._monitor_interval

    @property
    def stable_threshold_temp(self):
        return self._stable_threshold_temp

    @stable_threshold_temp.setter
    def stable_threshold_temp(self, temp):
        self._stable_threshold_temp = float(temp)

    @property
    def stable_threshold_pressure(self):
        return self._stable_threshold_pressure

    @stable_threshold_pressure.setter
    def stable_threshold_pressure(self, pressure_mpa):
        self._stable_threshold_pressure = float(pressure_mpa)

    @property
    def is_monitor_temp(self):
        return self._is_monitor_temp

    @is_monitor_temp.setter
    def is_monitor_temp(self, flag: bool):
        self._is_monitor_temp = bool(flag)

    @property
    def is_monitor_pressure(self):
        return self._is_monitor_pressure

    @is_monitor_pressure.setter
    def is_monitor_pressure(self, flag: bool):
        self._is_monitor_pressure = bool(flag)

    @property
    def force_stable(self):
        """
        force skip stable check, release all block call like 'wait_untill_temp_stable', just for debug maybe
        :return:
        """
        return self._is_force_stable

    @force_stable.setter
    def force_stable(self, flag: bool):
        self.force_stable = bool(flag)

    def _recv(self):
        logger.debug("recv th start run...")
        while True:

            try:
                header_bytes = self.socket.recv(7)

                if len(header_bytes) != 7:
                    continue

                header = ModBusHeader(header_bytes)

                if header.body_len <= 0:
                    logger.warning(f"tcp recv invalid body len: {header.body_len}")
                    continue

                logger.debug(f"tcp recv header: {tools.format_bytes(header_bytes)}")
                body_bytes = self.socket.recv(header.body_len)
                try:
                    body = ModBusBody(body_bytes)
                except ValueError:
                    logger.warning(f"tcp get wrong modbus body: {tools.format_bytes(body_bytes)}")
                    continue

                self._cur_resp_header = header
                self._cur_resp_body = body
                self._cur_resp_event.set()

            except ConnectionAbortedError:
                logger.info(f"tcp conn disconnect: {self.socket.getpeername()}")
                break

            except (socket.timeout, OSError):
                if self._is_open:
                    continue
                else:
                    logger.info("tcp client close, tcp recv thread quit")
                    break

            except Exception as err:
                logger.error("tcp recv thread error")
                logger.error(traceback.format_exc())
                raise err

        self.socket.close()

    def _send(self, byte: bytes) -> bytes:
        """
        send bytes to binder device
        :param byte:
        :return:
        """
        rest_len = len(byte) + 1
        header_bytes = (int.to_bytes(self._cur_trans_id, 2, byteorder='big') +
                        b'\x00\x00' +
                        int.to_bytes(rest_len, 2, byteorder='big') +
                        b'\xff')
        b = header_bytes + byte
        logger.debug(f"send all: {tools.format_bytes(b)}")
        self._cur_resp_event.clear()
        self.socket.sendall(b)
        self._cur_resp_event.wait()
        self._cur_trans_id += 1
        return self._cur_resp_body.byte

    def temp_setpoint(self, temp: float) -> float:
        """
        set temp setpoint
        :param temp:
        :return:
        """
        byte = (int.to_bytes(ModBusMsgType.WriteMultiReg, 1, "big") +
                int.to_bytes(self._wr_temp_setpoint_addr, 2, "big") +
                b'\x00\x02\x04')
        byte += get_byte_from_float(temp)
        self._send(byte)
        settemp = self.get_temp_setpoint()
        logger.debug(f"set temp setpoint {temp:.2f} C, confirm: {settemp:.2f}C")
        return settemp

    def get_temp_setpoint(self) -> float:
        """
        get current temp setpoint
        :return:
        """
        byte = (int.to_bytes(ModBusMsgType.ReadWrReg, 1, "big") +
                int.to_bytes(self._rd_temp_setpoint_addr, 2, "big") +
                b'\x00\x02')
        resp = self._send(byte)
        temp = get_float_from_byte(resp[2:6])
        logger.debug(f"get temp setpoint: {temp:.2f} C")
        return temp

    def get_temp(self) -> float:
        """
        get current temp
        :return:
        """
        byte = (int.to_bytes(ModBusMsgType.ReadHoldReg, 1, "big") +
                int.to_bytes(self._cur_temp_addr, 2, "big") +
                b'\x00\x02')
        resp = self._send(byte)
        temp = get_float_from_byte(resp[2:6])
        logger.debug(f"get temp: {temp:.2f} C")
        return temp

    def pressure_setpoint(self, mpa: float) -> float:
        """
        set pressure setpoint
        :param mpa:
        :return:
        """
        byte = (int.to_bytes(ModBusMsgType.WriteMultiReg, 1, "big") +
                int.to_bytes(self._wr_pressure_setpoint_addr, 2, "big") +
                b'\x00\x02\x04')
        byte += get_byte_from_float(mpa)
        self._send(byte)
        setpres = self.get_pressure_setpoint()
        logger.debug(f"set pressure setpoint{mpa:.2f} mpa, confirm: {setpres:.2f} mpa")
        return setpres

    def get_pressure_setpoint(self) -> float:
        """
        get current pressure setpoint
        :return:
        """
        byte = (int.to_bytes(ModBusMsgType.ReadWrReg, 1, "big") +
                int.to_bytes(self._rd_pressure_setpoint_addr, 2, "big") +
                b'\x00\x02')
        resp = self._send(byte)
        mpa = get_float_from_byte(resp[2:6])
        logger.debug(f"get pressure setpoint {mpa:.2f} mpa")
        return mpa

    def get_pressure(self) -> float:
        """
        get current pressure value
        :return:
        """
        byte = (int.to_bytes(ModBusMsgType.ReadHoldReg, 1, "big") +
                int.to_bytes(self._cur_pressure_addr, 2, "big") +
                b'\x00\x02')
        resp = self._send(byte)
        mpa = get_float_from_byte(resp[2:6])
        logger.debug(f"get pressure: {mpa:.2f} mpa")
        return mpa

    def disconnect(self):
        """
        disconnect from binder device
        :return:
        """
        self._is_open = False
        self.socket.close()

    def connect(self):
        """
        connect to binder device
        :return:
        """
        logger.info("binder connecting ...")
        self.socket.connect(self.server_addr)
        self.socket.settimeout(self.timeout)
        self._is_open = True
        self._recv_th = threading.Thread(target=self._recv)
        self._recv_th.start()
        logger.info("binder connected")

    def _monitor_temp(self, cur_temp: float, temp_setpoint: float):
        """
        will check for last stable threshold min, if all temp within threshold, will set stable event
        :param cur_temp:
        :param temp_setpoint:
        :return:
        """
        self._history_temp.append(cur_temp)
        self.latest_temp = cur_temp
        self.latest_temp_setpoint = temp_setpoint
        if len(self._history_temp) < self._stable_threshold:
            return

        self._history_temp = self._history_temp[-self._stable_threshold:]
        _max_err = max(abs(max(self._history_temp) - temp_setpoint),
                       abs(temp_setpoint - min(self._history_temp)))
        if _max_err <= self._stable_threshold_temp:
            self._temp_stable_event.set()
            logger.info(
                f"temp stable, temp_setpoint: {temp_setpoint:.2f}C, latest_temp: {self._history_temp[-1]:.2f}C, max_err: ±{_max_err:.2f}C")
        else:
            self._temp_stable_event.clear()

    def _monitor_pressure(self, cur_pressure: float, pressure_setpoint: float):
        """
        same as _monitor_temp, but for pressure
        :param cur_pressure:
        :param pressure_setpoint:
        :return:
        """
        self._history_pressure.append(cur_pressure)
        self.latest_pressure = cur_pressure
        self.latest_pressure_setpoint = pressure_setpoint
        if len(self._history_pressure) < self._stable_threshold:
            return

        self._history_pressure = self._history_pressure[-self._stable_threshold:]
        _max_err = max(abs(max(self._history_pressure) - pressure_setpoint),
                       abs(pressure_setpoint - min(self._history_pressure)))
        if _max_err <= self._stable_threshold_pressure:
            self._pressure_stable_event.set()
            logger.info(
                f"pressure stable, pressure_setpoint: {pressure_setpoint:.2f}mpa, latest_pressure: {self._history_pressure[-1]:.2f}mpa, max_err: ±{_max_err:.2f}mpa")
        else:
            self._pressure_stable_event.clear()

    def _monitor(self):
        logger.debug("binder monitor thread start ...")
        warn_cnt = 0
        while self._is_monitor_open:
            try:
                time.sleep(self._monitor_interval)

                if self._is_monitor_temp:
                    temp_setpoint = self.get_temp_setpoint()
                    cur_temp = self.get_temp()
                    self._monitor_temp(cur_temp, temp_setpoint)

                if self._is_monitor_pressure:
                    pres_setpoint = self.get_pressure_setpoint()
                    cur_pres = self.get_pressure()
                    self._monitor_pressure(cur_pres, pres_setpoint)

                if not any((self._is_monitor_temp, self._is_monitor_pressure)):
                    if warn_cnt > 5:
                        warn_cnt = 0
                        logger.warning("there is nothing to monitor, please set monitor flag")
                    else:
                        warn_cnt += 1

            except ConnectionAbortedError:
                logger.info(f"binder tcp conn disconnect: {self.socket.getpeername()}")
                break

            except (socket.timeout, OSError):
                if self._is_monitor_open:
                    continue
                else:
                    logger.info("binder monitor close, monitor thread quit")
                    break

            except Exception as err:
                logger.error("bingder tcp recv thread error")
                logger.error(traceback.format_exc())
                raise err

    def start_monitor(self, interval: int = 10, monitor_temp: bool = True, monitor_pressure: bool = False):
        """
        start monitor thread, monitor temp and pressure
        :param interval: sec
        :param monitor_temp:
        :param monitor_pressure:
        :return:
        """
        logger.info(
            f"binder monitor start at interval {interval}s, monitor temp: {monitor_temp}, monitor pressure: {monitor_pressure}")
        self._is_monitor_open = True
        self.monitor_interval = interval
        self.is_monitor_temp = monitor_temp
        self.is_monitor_pressure = monitor_pressure

        self._monitor_th = threading.Thread(target=self._monitor)
        self._monitor_th.start()

    def stop_monitor(self):
        self._is_monitor_open = False

    def wait_untill_temp_stable(self):
        """
        wait untill temp stable, if not stable, will keep block
        :return:
        """
        if not self._is_monitor_open:
            raise ValueError("open monitor first")
        elif not self.is_monitor_temp:
            raise ValueError("monitor temp is not open")

        if not self._is_force_stable:
            self._temp_stable_event.wait()

    def wait_untill_pressure_stable(self):
        """
        wait untill pressure stable, if not stable, will keep block
        :return:
        """
        if not self._is_monitor_open:
            raise ValueError("open monitor first")
        elif not self.is_monitor_pressure:
            raise ValueError("monitor pressure is not open")

        if not self._is_force_stable:
            self._pressure_stable_event.wait()
