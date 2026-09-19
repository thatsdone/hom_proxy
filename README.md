# hom_proxy : A simple HTTP proxy over MQTT

## Description

This is a foward proxy tool enabling connection from the Internet
to IoT devices behind firewalls over MQTT connections.

hom_proxy consists of the following 2 components.
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
Note that the target hostname (e.g. http://TARGET_HOST_NAME:PORT) is taken from
the topic that a hom_device.py instance subscribes as
'devices/TARGET_HOST_NAME/request'.

The above TARGET_HOST_NAME can be controlled from the hom_device.py side
using `--hostname` option. Also, they can be confirmed like below.

```
$ curl -sL  http://localhost:18080/command/subscriptions | jq '.'
{
  "code": 0,
  "data": [
    {
      "clientid": "hom_server",
      "topic": "devices/+/response",
      "qos": 1
    },
    {
      "clientid": "hom_server",
      "topic": "hom_server/control",
      "qos": 1
    },
    {
      "clientid": "iot-device1",
      "topic": "devices/iot-device1/request",
      "qos": 1
    }
  ]
}
```

In this case, you can acess to the iot-device1 like:
```
$ env http_proxy='http://localhost:18080' curl http://iot-device1/foo/bar
```
Note that you need to specify hostname in the MQTT topic above,
not the IP address of the device.

## Usage

0. Prepare MQTT broker
1. Install dependency packages
   * `$ pip install -r requirements.txt`
2. Start proxy server (in proxy directory)
   * `$ env MQTT_HOST=MQTT_HOST_IP uvicorn main:app [--debug] [--host HOST] [--port PORT]`
3. Start device connector (in device directory) on your IoT devices
   * `$ python3 hom_device.py --mqtt_host MQTT_HOST_IP [--debug]`
4. Now you can access to the device like below
   * `$ env http_proxy=http://HOM_PROXY_IP:PORT curl http://TARGET_HOST_NAME:TARGET_PORT/` etc.

### Notes
* hom_proxy supports http only. Does not work for https.
  Consider using MQTT over TLS (mqtts) as of now.
* Currently hom_device.py forwards requests to only localhost.
* Tested using NanoMQ(https://nanomq.io/).
* Administration features like 'GET /command/subscriptions' work for NanoMQ only.


### proxy

The proxy server of hom_proxy refers the following environment variables.
Specify at least MQTT_HOST to point your MQTT broker.

* HOM_DEBUG
* MQTT_HOST
* MQTT_PORT
* MQTT_TIMEOUT
* MQTT_QOS
* MQTT_MAX_CHUNK_SIZE
* HOM_REQUEST_TIMEOUT
* MQTT_TLS
* MQTT_TLS_INSECURE
* MQTT_CACERT
* MQTT_CERT
* MQTT_KEY

Regarding http proxy port, use `--port` option of uvicorn as of now.

In near future, hom_proxy will support to take a configuration file.

### hom_device.py


```
$ python3 hom_device.py --help
usage: hom_device.py [-h] [--debug] [--hostname HOSTNAME]
                     [--mqtt_version MQTT_VERSION] [--mqtt_host MQTT_HOST]
                     [--mqtt_port MQTT_PORT] [--topic TOPIC] [--qos QOS]
                     [--timeout TIMEOUT] [--tls] [--cacert CACERT] [--cert CERT]
                     [--key KEY] [--tls_secure] [--admin_bind ADMIN_BIND]
                     [--admin_port ADMIN_PORT]

hom_device.py

options:
  -h, --help            show this help message and exit
  --debug
  --hostname HOSTNAME
  --mqtt_version MQTT_VERSION
  --mqtt_host MQTT_HOST
  --mqtt_port MQTT_PORT
  --topic TOPIC
  --qos QOS
  --timeout TIMEOUT
  --tls
  --cacert CACERT
  --cert CERT
  --key KEY
  --tls_secure
  --admin_bind ADMIN_BIND
  --admin_port ADMIN_PORT
```


### Large messages

MQTT's protocol ceiling is 256MB, but almost no broker actually allows
messages that large -- most default to something between a few hundred
KB and a few MB. hom_proxy now transparently splits any payload larger
than a configurable size into several MQTT sub-messages on the same
topic, and reassembles them on the receiving end, so message size is no
longer bounded by the broker's per-message limit.

* Controlled by `MQTT_MAX_CHUNK_SIZE` (proxy, bytes, default 262144) and
  `--max_chunk_size` (hom_device.py, same default). Set this comfortably
  under your broker's configured message size limit.
* `HOM_REQUEST_TIMEOUT` (proxy, seconds, default 10) controls how long
  the proxy waits for a full response before returning HTTP 503. A very
  large response, or a low `MQTT_MAX_CHUNK_SIZE`, means more chunks and
  more time in transit, so this may need to be raised alongside it.
* This is a wire-format change: a proxy and device connector must both
  be running the version that supports chunked messages. They can no
  longer interoperate with older, pre-chunking versions of the other
  component.

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
* many
