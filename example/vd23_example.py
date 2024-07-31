import time

from pyaptcom4.VD import VD23

if __name__ == '__main__':
    box = VD23('192.168.211.36')
    box.connect()
    while True:
        time.sleep(3)
        print("cur_temp", box.get_temp())
        print("cur_pressure", box.get_pressure())
        print("set temp", box.temp_setpoint(25))
        print("set pressure", box.pressure_setpoint(1000))
        print("get set_temp", box.get_temp_setpoint())
        print("get set_pressure", box.get_pressure_setpoint())
        print()
