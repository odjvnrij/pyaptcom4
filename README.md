pyaptcom4
=======================================
When the device is connected through network cables, 
BINDER device use modbus tcp protocol, so we can use pyaptcom4 to call it.
pyaptcom4 provides basic api like get_temp, get_pressure to get basic value



how to install?
---------------
```bash
pip install pyaptcom4.whl
```
or 
```bash
pip install pyaptcom4
```



how to use?
---------------
```python3
from pyaptcom4.VD import VD23

box = VD23('192.168.211.36')
box.connect()
print("cur_temp", box.get_temp())
print("cur_pressure", box.get_pressure())
box.disconnect()
```


or jsut see [example](example)

