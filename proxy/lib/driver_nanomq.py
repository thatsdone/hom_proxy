#!/usr/bin/env python3
#
# hom_proxy: A simple Http Over MQTT proxy
#
# License:
#   Apache License, Version 2.0
# History:
#   * 2026/08/04 v0.1 Initial version
# Author:
#   Masanori Itoh <masanori.itoh@gmail.com>
import base64
import json

import requests
from shared import config


def get_subscriptions():

    nanomq_host = config.get('mqtt_host', None)
    if not nanomq_host:
        nanomq_host = '192.168.0.1'
    nanomq_api_port = 8081

    base_url = f'http://{nanomq_host}:{nanomq_api_port}/api/v4'
    headers = {}
    # TODO: Allow configuration of NanoMQ admin credentials
    token = base64.b64encode(b'admin:public').decode('utf-8')
    headers['Authorization'] = f'Basic {token}'
    url = base_url + '/' + 'subscriptions'
    timeout = 3
    r = requests.get(url, headers=headers, timeout=timeout)
    return json.loads(r.text)

