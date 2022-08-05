#
# File:   rp2040_ndsp.py
# Date:   25-Jul-2022
# Author: I. Chuang <ichuang@mit.edu>
#
'''
NDSP server which runs on an RP2040 embedded processor, connected to a
W5500 wiznet ethernet interface, using Adafruit's CircuitPython. 
Specifically, this was tested using a waveshare RP2040-zero (with 
neopixel LED), and a W5500 module.

This code uses a very rudimentary NDSP framework which does *not* use sipyco, 
but can run a remote procedure, accepting basic python data types and
returning basic python data types.

ExampleNDSP is the demo NDSP provided in this code, and it has methods 
for adding two numbers, printing a message, and setting the R, G, B colors
of the on-board neopixel LED on-board.

Does not require numpy.  Note that because "inspect" is unavailable in
CircuitPython, arguments of functions cannot be programmatically determined, 
and docstrings are unavailable.

-----------------------------------------------------------------------------
Test this code by running sipyco_rpctool, e.g. as follows:

$ sipyco_rpctool 192.168.1.221 3476 call -t rp2040_ndsp ping
'Example NDSP is alive!'

$ sipyco_rpctool 192.168.1.221 3476 list-targets
Target(s):   rp2040_ndsp
Description: rp2040 NDSP

$ sipyco_rpctool 192.168.1.221 3476 call -t rp2040_ndsp print "'hello world'"

$ sipyco_rpctool 192.168.1.221 3476 call -t rp2040_ndsp led 4 200 0

$ sipyco_rpctool 192.168.1.221 3476 call -t rp2040_ndsp add 9 14
23

$ sipyco_rpctool 192.168.1.221 3476 list-methods
docstring not available on RP2040

add()
    unavailable

led()
    unavailable

ping()
    unavailable

print()
    unavailable

-----------------------------------------------------------------------------
Here is a sample ARTIQ experiment calling this NDSP:

from artiq.experiment import *

class DummyNDSP(EnvExperiment):

    def build(self):
	self.setattr_device("rp2040")

    def run(self):
	result = self.rp2040.ping()
	print("ping = ", result)

	ret = self.rp2040.add(3, 15)
	print("add result = ", ret)

	# flash LED blue for a moment
	self.rp2040.led(0, 0, 255) # r, g, b
        self.rp2040.led(0, 0, 0)   # r, g, b

'''

import time
import board
import busio
import pwmio
import neopixel
import digitalio
import traceback

from adafruit_wiznet5k.adafruit_wiznet5k import WIZNET5K
import adafruit_wiznet5k.adafruit_wiznet5k_socket as socket

VERBOSE_DEBUG = True

#-----------------------------------------------------------------------------

class MyPyon:
    '''
    Dummy replacement for sipyco.pyon (python object notation) which returns a string version
    of a python object
    '''
    def __init__(self):
        return

    def encode(self, obj):
        return repr(obj)

    def decode(self, line):
        try:
            obj = line.decode()	# default - return string
        except Exception as err:
            obj = line
        if line.startswith("{") or line.startswith("["):
            try:
                obj = eval(line)
            except Exception as err:
                pass
        return obj

#-----------------------------------------------------------------------------

class MySocket(socket.socket):
    '''
    Version of the adafruit wiznet5k socket class, with a different readline method
    '''
    
    def readline(self):
        """Attempt to return as many bytes as we can up to
        but not including '\n' (newline).	

        This differes from the adafruit socket's readline in that
        the line is expected to terminate in just the newline, with no
        carridge return needed.

        Also, in event of a timeout, return an empty string, instead of 
        raising an exception.
        """
        stamp = time.monotonic()
        while b"\n" not in self._buffer:
            avail = self.available()
            if avail:
                if self._sock_type == socket.SOCK_STREAM:
                    self._buffer += socket._the_interface.socket_read(self.socknum, avail)[1]
                elif self._sock_type == socket.SOCK_DGRAM:
                    self._buffer += socket._the_interface.read_udp(self.socknum, avail)[1]
            if (
                not avail
                and self._timeout > 0
                and time.monotonic() - stamp > self._timeout
            ):
                return ""	# instead of raising error, just return empty line
                #self.close()
                #raise RuntimeError("Didn't receive response, failing out...")
        firstline, self._buffer = self._buffer.split(b"\n", 1)
        socket.gc.collect()
        return firstline

#-----------------------------------------------------------------------------

class SocketServerForWiznet:
    '''
    TCP SocketServer-like class, for Adafruit's CircuitPython Wiznet5k library
    Just uses socket calls.
    Not multithreaded.
    '''
    TIMEOUT = 5
    
    def __init__(self, host="", port=None):
        self.host = host
        self.port = port
        self.init_socket()

    def init_socket(self):
        print(f"Create TCP Server Socket host={self.host}, port={self.port}")
        self.sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        # self.sock.settimeout(self.TIMEOUT)
    
        self.sock.bind((self.host, self.port))
        self.sock.listen()
        print(f"Socket initialized on port {self.port}")
        
    def serve_forever(self):
        '''
        Main TCP/IP socket listening loop
        '''
        while True:
            print("[SocketServerForWiznet] Accepting connections")
            conn, addr = self.sock.accept()
            if not conn:
                print("conn is None!  Sleeping then restarting")
                time.sleep(2)
                continue
            print("Accepted from", addr)
            self.wfile = conn
            self.rfile = MySocket()		# replace socket with local version that has different readline() method
            self.rfile._socknum = conn._socknum
            self.rfile._timeout = 1		# timeout after 1 second on readline
        
            if 0:
                buf = conn.recv(128)		# for debugging
                print(f"received buf=", buf)

            self.handle()
        
            try:
                conn.close()
            except Exception as err:
                pass

    def __enter__(self):
        '''
        Called on entrance when instantiated using with...
        '''
        return

    def __exit__(self):
        '''
        Called on exit when instantiated using with...
        '''
        try:
            self.wfile.close()
        except Exception as err:
            pass

    def handle(self):
        '''
        Subclass should define this
        '''
        pass

#-----------------------------------------------------------------------------

class NanoNDSPServer(SocketServerForWiznet):
    '''
    TCP/IP socket server for NDSP.
    This version is single-thread, but could re-mix this to make it threaded.
    '''
    allow_reuse_address = True
    def __init__(self, targets, description="", host="localhost", port=3478):
        '''
        targets = (dict) dict of {procedure_name, <procedure>, ...}
        description = (str) string description of this server
        host = (str) hostname or IP address to bind port on
        port = (int) TCP/IP port number to use
        '''
        self.pyon = MyPyon()
        self.targets = targets
        self.description = description
        self.server = self
        super().__init__(host, port)

#-----------------------------------------------------------------------------

class NanoNDSP(NanoNDSPServer):
    """
    Handler for NDSP server which does not need sipyco, and only uses python sockets.
    This version does not use asyncio; it is a handler for a TCP/IP socketserver.

    Basic protocol:
    
    [MyServer] Received 1: 'b'ARTIQ pc_rpc\n''
    [MyServer] Received 2: 'b'example_adder\n''
    [MyServer] Received 3: 'b'{"action": "call", "name": "add", "args": (4, 9), "kwargs": {}}\n''
    [MyServer] sending: '{"status": "ok", "ret": 13}'
    [MyServer] Received 4: 'b'''

    """
    _init_string = b"ARTIQ pc_rpc\n"

    def _process_action(self, target, obj):
        '''
        Perform requested action (specified in obj) to specified target
        '''
        try:
            if obj["action"] == "get_rpc_method_list":
                members = set([ x for x in dir(target) if not x.startswith("__")])
                doc = {
                    "docstring": "docstring not available on RP2040",
                    "methods": {}
                }
                for name in members:
                    if name.startswith("_"):
                        continue
                    doc["methods"][name] = ({'args': [], 'varargs': None, 'varkw': None, 'defaults': None,
                                             'kwonlyargs': [], 'kwonlydefaults': None, 'annotations': {}},
                                            'unavailable')
                if VERBOSE_DEBUG:
                    print("[_process_action]: RPC docs for %s: %s", target, doc)
                return doc
            elif obj["action"] == "call":
                if VERBOSE_DEBUG:
                    print(f"[_process_action]: calling {obj}")
                method = getattr(target, obj["name"])
                ret = method(*obj["args"], **obj["kwargs"])
                return ret
            else:
                raise ValueError("Unknown action: {}"
                                 .format(obj["action"]))

        except Exception as err:
            print(f"Failed to run {target} with obj={obj}, err={err}")
            raise

    def _process_and_pyonize(self, target, obj):
        '''
        Call target procedure, encode return using pyon, and return dict with status ok
        '''
        try:
            ret = self._process_action(target, obj)
            return self.server.pyon.encode({
                "status": "ok",
                "ret": ret,
            })
        except Exception as err:
            print(f"[NanoNDSPServer] Error!  {err}")
            # raise
            return self.server.pyon.encode({
                "status": "failed",
                "exception": str(err),
            })

    def handle(self):
        reader = self.rfile        # self.rfile is a file-like object created by the handler
        writer = self.wfile
        pyon = self.server.pyon

        try:
            linecnt = 0
            line = reader.readline()

            linecnt += 1
            if VERBOSE_DEBUG:
                print(f"[NanoNDSP] Received {linecnt}: '{line}'")

            if line.strip() != self._init_string.strip():
                return

            obj = {
                "targets": sorted(self.server.targets.keys()),
                "description": self.server.description
            }
            line = pyon.encode(obj) + "\n"
            writer.send(line.encode())
            line = reader.readline()
            if not line:
                if VERBOSE_DEBUG:
                    print(f"[NanoNDSP] Received empty line at {linecnt}")
                return

            linecnt += 1
            if VERBOSE_DEBUG:
                print(f"[NanoNDSP] Received {linecnt}: '{line}'")

            target_name = line.decode().strip()
            print(f"[NanoNDSP] Instantiating target {target_name}")
            try:
                target = self.server.targets[target_name]
            except KeyError as err:
                print(f"[NanoNDSP] Oops!  Failed to instantiate target, err={err}")
                return

            if callable(target):
                target = target()

            valid_methods = set([ x for x in dir(target) if not x.startswith("__")])	# inspect not available in CircuitPython
            msg = (pyon.encode(valid_methods) + "\n").encode()
            if VERBOSE_DEBUG:
                print(f"[NanoNDSP] replying with msg={msg}")
            writer.send(msg)

            while True:
                if VERBOSE_DEBUG:
                    print(f"[NanoNDSP] Waiting for lines...")
                line = reader.readline()

                linecnt += 1
                if VERBOSE_DEBUG:
                    print(f"[NanoNDSP] Received {linecnt}: '{line}'")

                if not line:
                    break
                reply = self._process_and_pyonize(target, pyon.decode(line.decode()))

                if VERBOSE_DEBUG:
                    print(f"[NanoNDSP] sending: '{reply}'")
                writer.send((reply + "\n").encode())

        except Exception as err:
            print(f"Failed!  err={err}")
            raise
        finally:
            writer.close()

#-----------------------------------------------------------------------------

led_device = neopixel.NeoPixel(board.GP16, 1)

class ExampleNDSP:
    def __init__(self):
        print("ExampleNDSP initialized")

    def ping(self):
        '''
        return a message
        '''
        return("Example NDSP is alive!")

    def add(self, a, b):
        '''
        Add two numbers and return result
        '''
        return a+b

    def print(self, msg):
        '''
        Print message
        '''
        print(msg)

    def led(self, r, g, b):
        '''
        set RP2040 neopixel LED values
        r, g, b should be integers in the range 0, 255
        '''
        led_device[0] = (r, g, b)

#-----------------------------------------------------------------------------

def RunNDSPServer(app_class, description="rp2040 NDSP", port=3476):

    # change these networking parameters to those desired 

    IP_ADDRESS = (192, 168, 1, 221)				# change this to be the desired IP address
    MY_MAC = (0x00, 0x01, 0x02, 0x03, 0x04, IP_ADDRESS[-1])	# this should be changed to be unique for each RP2040 on the network
    SUBNET_MASK = (255, 255, 255, 0)
    GATEWAY_ADDRESS = (192, 168, 1, 100)
    DNS_SERVER = (8, 8, 8, 8)

    print("rp2040_ndsp with Wiznet5k (fixed IP=%s)" % str(IP_ADDRESS))

    # start with LED red
    led_device[0] = (40, 0, 0)

    # initialize the Wiznet5500 ethernet interface (may also work with the W5100)

    SPI0_SCK = board.GP10
    SPI0_TX = board.GP11
    SPI0_RX = board.GP12
    SPI0_CSn = board.GP13
    W5x00_RSTn = board.GP14		## wiznet reset

    ethernetRst = digitalio.DigitalInOut(W5x00_RSTn)
    ethernetRst.direction = digitalio.Direction.OUTPUT

    spi_bus = busio.SPI(SPI0_SCK, MOSI=SPI0_TX, MISO=SPI0_RX)
    cs = digitalio.DigitalInOut(SPI0_CSn)	# wiznet chip select

    # Reset W5500 first
    ethernetRst.value = False
    time.sleep(0.5)
    ethernetRst.value = True

    # Initialize ethernet interface without DHCP
    eth = WIZNET5K(spi_bus, cs, is_dhcp=False, mac=MY_MAC, debug=False)
    # Initialize ethernet interface with DHCP
    # eth = WIZNET5K(spi_bus, cs, is_dhcp=True, mac=MY_MAC, debug=False)
    
    # Set network configuration
    eth.ifconfig = (IP_ADDRESS, SUBNET_MASK, GATEWAY_ADDRESS, DNS_SERVER)
    HOST = eth.pretty_ip(eth.ip_address)
    
    print("Chip Version:", eth.chip)
    print("MAC Address:", [hex(i) for i in eth.mac_address])
    print("My IP address is:", eth.pretty_ip(eth.ip_address))

    socket.set_interface(eth)

    dev = app_class()
    print(f"Starting sample NDSP server on port {port}")
    
    # blink LED blue to let user know the server is coming up
    led_device[0] = (0, 0, 40)
    time.sleep(0.25)
    led_device[0] = (0, 0, 0)

    targets = {"rp2040_ndsp": dev}
    server = NanoNDSP(targets, description=description, host=HOST, port=port)
    
    # blink LED green to let user know the server is listening
    led_device[0] = (0, 40, 0)
    time.sleep(0.25)
    led_device[0] = (0, 0, 0)

    server.serve_forever()

#-----------------------------------------------------------------------------

RunNDSPServer(ExampleNDSP)
