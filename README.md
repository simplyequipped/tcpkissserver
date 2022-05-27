# TCP KISS Server
TCP [KISS](https://en.wikipedia.org/wiki/KISS_(TNC)) server for connecting software applications to [Reticulum](https://github.com/markqvist/Reticulum) using its built-in TCP client interface (with kiss framing enabled).

### Reticulum Configuration
Reticulum will need to be configured appropriately to interact with the TCP KISS server. Using the default server IP address and port number would look like this:
```
[[TCP KISS Interface]]
    type = TCPClientInterface
    interface_enabled = True
    kiss_framing = True
    target_host = 127.0.0.1
    target_port = 8001
```
See the [TCP Client Interface section in the Reticulum manual](https://markqvist.github.io/Reticulum/manual/interfaces.html#tcp-client-interface) for more information.

Note that the server IP address and port number are configurable:
```
server = tcpkissserver.Server(bind_ip='192.168.0.5', bind_port=8005, tx_callback=my_function)
```
Be sure to configure Reticulum to match.

### Example
```
import fskmodem
import tcpkissserver

modem = fskmodem.Modem()
server = tcpkissserver.Server(tx_callback=modem.send)
modem.set_rx_callback(server.receive)
```

Data received by the modem will be passed to the server which will then pass the data to Reticulum.
Data sent by Reticulum will be received by the server which will then pass the data to the modem for transmitting.
