# MIT License
#
# Copyright (c) 2016-2022 Mark Qvist / unsigned.io
#
# Permission is hereby granted, free of charge, to any person obtaining a copy
# of this software and associated documentation files (the "Software"), to deal
# in the Software without restriction, including without limitation the rights
# to use, copy, modify, merge, publish, distribute, sublicense, and/or sell
# copies of the Software, and to permit persons to whom the Software is
# furnished to do so, subject to the following conditions:
#
# The above copyright notice and this permission notice shall be included in all
# copies or substantial portions of the Software.
#
# THE SOFTWARE IS PROVIDED "AS IS", WITHOUT WARRANTY OF ANY KIND, EXPRESS OR
# IMPLIED, INCLUDING BUT NOT LIMITED TO THE WARRANTIES OF MERCHANTABILITY,
# FITNESS FOR A PARTICULAR PURPOSE AND NONINFRINGEMENT. IN NO EVENT SHALL THE
# AUTHORS OR COPYRIGHT HOLDERS BE LIABLE FOR ANY CLAIM, DAMAGES OR OTHER
# LIABILITY, WHETHER IN AN ACTION OF CONTRACT, TORT OR OTHERWISE, ARISING FROM,
# OUT OF OR IN CONNECTION WITH THE SOFTWARE OR THE USE OR OTHER DEALINGS IN THE
# SOFTWARE.
#
# Modified by OtisByron / 2022


import socketserver
import threading
import platform
import socket
import time

class KISS():
    FEND              = 0xC0
    FESC              = 0xDB
    TFEND             = 0xDC
    TFESC             = 0xDD
    CMD_DATA          = 0x00
    CMD_UNKNOWN       = 0xFE

    @staticmethod
    def escape(data):
        data = data.replace(bytes([0xdb]), bytes([0xdb, 0xdd]))
        data = data.replace(bytes([0xc0]), bytes([0xdb, 0xdc]))
        return data

class ThreadingTCPServer(socketserver.ThreadingMixIn, socketserver.TCPServer):
    pass

class TCPKISSClient:
    RECONNECT_WAIT = 5
    RECONNECT_MAX_TRIES = None

    # TCP socket options
    TCP_USER_TIMEOUT = 20
    TCP_PROBE_AFTER = 5
    TCP_PROBE_INTERVAL = 3
    TCP_PROBES = 5

    def __init__(self, target_ip=None, target_port=None, connected_socket=None, max_reconnect_tries=None, kiss_framing=True):
        self.socket           = None
        self.initiator        = False
        self.reconnecting     = False
        self.never_connected  = True
        self.writing          = False
        self.online           = False
        self.detached         = False
        self.kiss_framing     = kiss_framing
        self.MTU              = 500
        self.tx_callback      = None
        
        if max_reconnect_tries == None:
            self.max_reconnect_tries = TCPKISSClient.RECONNECT_MAX_TRIES
        else:
            self.max_reconnect_tries = max_reconnect_tries

        if connected_socket != None:
            self.receives    = True
            self.target_ip   = None
            self.target_port = None
            self.socket      = connected_socket

            if platform.system() == "Linux":
                self.set_timeouts_linux()
            elif platform.system() == "Darwin":
                self.set_timeouts_osx()

        elif target_ip != None and target_port != None:
            self.receives    = True
            self.target_ip   = target_ip
            self.target_port = target_port
            self.initiator   = True
            
            if not self.connect(initial=True):
                thread = threading.Thread(target=self.reconnect)
                thread.setDaemon(True)
                thread.start()
            else:
                thread = threading.Thread(target=self.read_loop)
                thread.setDaemon(True)
                thread.start()

    def set_timeouts_linux(self):
        self.socket.setsockopt(socket.IPPROTO_TCP, socket.TCP_USER_TIMEOUT, int(TCPKISSClient.TCP_USER_TIMEOUT * 1000))
        self.socket.setsockopt(socket.SOL_SOCKET, socket.SO_KEEPALIVE, 1)
        self.socket.setsockopt(socket.IPPROTO_TCP, socket.TCP_KEEPIDLE, int(TCPKISSClient.TCP_PROBE_AFTER))
        self.socket.setsockopt(socket.IPPROTO_TCP, socket.TCP_KEEPINTVL, int(TCPKISSClient.TCP_PROBE_INTERVAL))
        self.socket.setsockopt(socket.IPPROTO_TCP, socket.TCP_KEEPCNT, int(TCPKISSClient.TCP_PROBES))

    def set_timeouts_osx(self):
        if hasattr(socket, "TCP_KEEPALIVE"):
            TCP_KEEPIDLE = socket.TCP_KEEPALIVE
        else:
            TCP_KEEPIDLE = 0x10

        self.socket.setsockopt(socket.SOL_SOCKET, socket.SO_KEEPALIVE, 1)
        
        self.socket.setsockopt(socket.IPPROTO_TCP, TCP_KEEPIDLE, int(TCPKISSClient.TCP_PROBE_AFTER))
        
    def detach(self):
        if self.socket != None:
            if hasattr(self.socket, "close"):
                if callable(self.socket.close):
                    self.detached = True
                    
                    try:
                        self.socket.shutdown(socket.SHUT_RDWR)
                    except Exception as e:
                        pass

                    try:
                        self.socket.close()
                    except Exception as e:
                        pass

                    self.socket = None

    def connect(self, initial=False):
        try:
            self.socket = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
            self.socket.connect((self.target_ip, self.target_port))
            self.online  = True
        
        except Exception as e:
            if initial:
                return False
            
            else:
                raise e

        if platform.system() == "Linux":
            self.set_timeouts_linux()
        elif platform.system() == "Darwin":
            self.set_timeouts_osx()
        
        self.online  = True
        self.writing = False
        self.never_connected = False

        return True


    def reconnect(self):
        if self.initiator:
            if not self.reconnecting:
                self.reconnecting = True
                attempts = 0
                while not self.online:
                    time.sleep(TCPKISSClient.RECONNECT_WAIT)
                    attempts += 1

                    if self.max_reconnect_tries != None and attempts > self.max_reconnect_tries:
                        self.teardown()
                        break

                    try:
                        self.connect()

                    except Exception as e:
                        pass

                if not self.never_connected:
                    pass

                self.reconnecting = False
                thread = threading.Thread(target=self.read_loop)
                thread.setDaemon(True)
                thread.start()
    def send(self, data):
        self.tx_callback(data)

    def receive(self, data):
        if self.online:
            while self.writing:
                time.sleep(0.01)

            try:
                self.writing = True

                if self.kiss_framing:
                    data = bytes([KISS.FEND])+bytes([KISS.CMD_DATA])+KISS.escape(data)+bytes([KISS.FEND])

                self.socket.sendall(data)
                self.writing = False

            except Exception as e:
                self.teardown()

    def set_tx_callback(self, callback):
        self.tx_callback = callback

    def read_loop(self):
        try:
            in_frame = False
            escape = False
            data_buffer = b""
            command = KISS.CMD_UNKNOWN

            while True:
                data_in = self.socket.recv(4096)
                if len(data_in) > 0:
                    pointer = 0
                    while pointer < len(data_in):
                        byte = data_in[pointer]
                        pointer += 1

                        if self.kiss_framing:
                            # Read loop for KISS framing
                            if (in_frame and byte == KISS.FEND and command == KISS.CMD_DATA):
                                in_frame = False
                                self.send(data_buffer)
                            elif (byte == KISS.FEND):
                                in_frame = True
                                command = KISS.CMD_UNKNOWN
                                data_buffer = b""
                            elif (in_frame and len(data_buffer) < self.MTU):
                                if (len(data_buffer) == 0 and command == KISS.CMD_UNKNOWN):
                                    # We only support one HDLC port for now, so
                                    # strip off the port nibble
                                    byte = byte & 0x0F
                                    command = byte
                                elif (command == KISS.CMD_DATA):
                                    if (byte == KISS.FESC):
                                        escape = True
                                    else:
                                        if (escape):
                                            if (byte == KISS.TFEND):
                                                byte = KISS.FEND
                                            if (byte == KISS.TFESC):
                                                byte = KISS.FESC
                                            escape = False
                                        data_buffer = data_buffer+bytes([byte])

                else:
                    self.online = False
                    if self.initiator and not self.detached:
                        self.reconnect()
                    else:
                        self.teardown()

                    break

                
        except Exception as e:
            self.online = False

            if self.initiator:
                self.reconnect()
            else:
                self.teardown()

    def teardown(self):
        self.online = False

    def __str__(self):
        return "TCPKISS[" + str(self.target_ip) + ":" + str(self.target_port) + "]"


class TCPKISSServer:
    def __init__(self, bindip="127.0.0.1", bindport=8001, tx_callback=None):
        self.online = False
        self.clients = []
        self.tx_callback = tx_callback

        if (bindip != None and bindport != None):
            self.receives = True
            self.bind_ip = bindip
            self.bind_port = bindport

            def handlerFactory(callback):
                def createHandler(*args, **keys):
                    return TCPInterfaceHandler(callback, *args, **keys)
                return createHandler

            address = (self.bind_ip, self.bind_port)

            ThreadingTCPServer.allow_reuse_address = True
            self.server = ThreadingTCPServer(address, handlerFactory(self.incoming_connection))

            thread = threading.Thread(target=self.server.serve_forever)
            thread.setDaemon(True)
            thread.start()

            self.online = True


    def incoming_connection(self, handler):
        spawned_interface = TCPKISSClient(target_ip=None, target_port=None, connected_socket=handler.request)
        spawned_interface.target_ip = handler.client_address[0]
        spawned_interface.target_port = str(handler.client_address[1])
        spawned_interface.online = True
        self.clients.append(spawned_interface)
        spawned_interface.set_tx_callback(self.tx_callback)
        spawned_interface.read_loop()

    def receive(self, data):
        for client in self.clients:
            client.receive(data)

    def processOutgoing(self, data):
        pass

    def __str__(self):
        return "TCPKISSServer[" + str(self.bind_ip) + ":" + str(self.bind_port) + "]"

class TCPInterfaceHandler(socketserver.BaseRequestHandler):
    def __init__(self, callback, *args, **keys):
        self.callback = callback
        socketserver.BaseRequestHandler.__init__(self, *args, **keys)

    def handle(self):
        self.callback(handler=self)
        
