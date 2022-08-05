# rp2040_ndsp

[`rp2040_ndsp.py`](rp2040_ndsp.py) is a stripped-down, simple NDSP server which runs on an RP2040 embedded processor, e.g. a Waveshare <a href="https://www.waveshare.com/rp2040-zero.htm">RP2040-Zero board</a> connected to a <a href="https://www.amazon.com/HiLetgo-Ethernet-Network-Interface-WIZ820io/dp/B08KXM8TKJ">W5500 ethernet network module</a>:

<img src="images/PHOTO-rp2040-ethernet-2022-07-25a.png"></img>

The RP2040 is like a miniature Raspberry PI, and it is used to run <a href="https://learn.adafruit.com/welcome-to-circuitpython/what-is-circuitpython">Adafruit's CircuitPython</a>, with the <a href="https://learn.adafruit.com/ethernet-for-circuitpython">Wiznet5k Ethernet library</a>.  This setup offers 29 multifunction GPIO pins (including four ADC channels) for control by an NDSP:

<img src="images/RP2040-Zero-details-7.jpg"></img>

This NDSP server can be called from ARTIQ; see [`rp2040_experiment.py`](rp2040_experiment.py) for example.
A convenient way to test this is using the <a href="https://github.com/Technosystem-Labs/dartiq">dartiq</a> dockerized ARTIQ package.  Install that package, enter this into `device_db.py`:
```
device_db = {
    # rp2040 nano NDSP
    "rp2040": {
	"type": "controller",
        "host": "192.168.1.221",
        "port": 3476,
    },
}
```
then run:
```
    dartiq run "artiq_run ./rp2040_experiment.py"
```
and you should see:
```
ping =  Example NDSP is alive!
add result =  18
```
