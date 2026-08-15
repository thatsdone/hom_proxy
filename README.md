# hom_proxy : A simple HTTP proxy over MQTT

## Description

This is a foward proxy tool enabling connection from the Internet
to IoT devices behind firewalls over MQTT connections.

hom_proxy composed of 2 components:
* proxy server: behaves as a conventional forward proxy
* device connector: connects to the proxy server and forward messages internally

```
                                  |
+-----------+     +------------+  |  +-----------+     +-----------+ 
| private   |<----| hom_device |---->| MQTT      |<----| hom_proxy |
| service   | HTTP| connector  |MQTT | Broker    |MQTT |           |
+-----------+     +------------+  |  +-----------+     +-----------+
                                  |                          ^
  Private Network (e.g. Cellular) |  Internet                | HTTP
                                  |                          |
                               Firewall                +-----------+
                                                       | HTTP      |
                                                       | client    |
                                                       +-----------+ 
```

Note that the target hostname (e.g. http://TARGET_HOAT_NAME:PORT) is taken from
the topic that a hom_device.py instance ubscribes as
'devices/RARGET_HOST_NAME/request'.

## Usage

0. Prepare MQTT broker
1. Install dependency packages
   * `$ pip install -r requirements.txt`
2. Start proxy server
   * `$ env MQTT_HOST=MQTT_HOST_IP uvicorn main:app [--debug]`
3. Start device connector (tools/hom_device.py) on your IoT devices
   * `$ python3 hom_device.py --mqtt_host MQTT_HOST_IP [--debug]`

## Notes
* hom_proxy supports http only. Does not work for https.
  Consider using MQTT over TLS for now.
* Currently hom_device.py forward requests to only localhost.
* Tested using NanoMQ(https://nanomq.io/).
* Administration features like 'GET /command/subscriptions' work for NanoMQ only.

## License
Apache License, Version 2.0

## Author
Masanori Itoh <masanori.itoh@gmail.com>

## References
* python-proxy
  * https://github.com/qwj/python-proxy
* HttpOverMQTT
  * https://github.com/BrandtHill/HttpOverMqtt/
* Waziup
  * https://github.com/Waziup/
## TODO
* Support for MQTT over TLS.
* Support large messages (more than 256MB).
* many
