#!/usr/bin/env python3
#
# hom: A simple Http Over MQTT proxy
#
# License:
#   Apache License, Version 2.0
# History:
#   * 2026/08/04 v0.1 Initial version
# Author:
#   Masanori Itoh <masanori.itoh@gmail.com>
# TODO:
#   * many
import importlib
import logging
import os
import pickle
import sys
import time
import urllib
import uuid
from contextlib import asynccontextmanager

import paho.mqtt.client as mqtt
from fastapi import FastAPI, Request
from starlette.middleware.base import BaseHTTPMiddleware

from routers import commands, passthrough
from shared import config, devices, pending_requests

config['debug'] = False
hom_debug = os.getenv('HOM_DEBUG')
if hom_debug and int(hom_debug) != 0:
    config['debug'] = True
config['verbose'] = False

logger = logging.getLogger('hom_server')
log_level = 'DEBUG' if config['debug'] else 'INFO'
logger.setLevel(log_level)
formatter = logging.Formatter(
    fmt = '%(asctime)s.%(msecs)03d %(levelname)s: %(message)s',
    datefmt='%Y/%m/%d %H:%M:%S')
streamHandler = logging.StreamHandler(sys.stdout)
streamHandler.setFormatter(formatter)
logger.addHandler(streamHandler)

@asynccontextmanager
async def lifespan(app: FastAPI):
    logger.info('Starting...')

    mqtt_driver_name = os.getenv('MQTT_DRIVER', 'nanomq')
    config['mqtt_driver'] = importlib.import_module(f'lib.driver_{mqtt_driver_name}')
    if not config['mqtt_driver']:
        logger.error(f'Failed to load MQTT_DRIVER: {mqtt_driver_name}')
        sys.exit()

    mqtt_version = 5
    config['mqtt_version'] = 5
    mqtt_host = os.getenv('MQTT_HOST')
    if not mqtt_host:
        mqtt_host = '192.168.0.1'
    config['mqtt_host'] = mqtt_host
    mqtt_port  = os.getenv('MQTT_PORT', 1883)
    config['mqtt_tls'] = mqtt_port
    mqtt_timeout = os.getenv('MQTT_TIMEOUT')
    if not mqtt_timeout:
        mqtt_timeout = 60
    else:
        mqtt_timeout = int(mqtt_timeout)
    config['mqtt_timeout'] = mqtt_timeout
    mqtt_qos = os.getenv('MQTT_QOS')
    if not mqtt_qos:
        mqtt_qos = 1
    else:
        mqtt_qos = int(mqtt_qos)
    config['mqtt_qos'] = mqtt_qos
    
    mqtt_tls = bool(os.getenv('MQTT_TLS', False))
    if mqtt_tls and mqtt_port == 1883:
        # set default mqtts port
        mqtt_port = 8883
    config['mqtt_port'] = int(mqtt_port)
    # cacert
    mqtt_cacert = os.getenv('MQTT_CACERT', None)
    config['mqtt_cacert'] = mqtt_cacert
    mqtt_tls_insecure = bool(os.getenv('MQTT_TLS_INSECURE', False))
    config['mqtt_tls_insecure'] = mqtt_tls_insecure
    # client certificate and key
    mqtt_cert = os.getenv('MQTT_CERT', None)
    config['mqtt_cert'] = mqtt_cert
    mqtt_key = os.getenv('MQTT_KEY', None)
    config['mqtt_key'] = mqtt_key

    userdata = 'server'
    if config['mqtt_version'] == 3:
        mqttv = mqtt.MQTTv31
    else:
        mqttv = mqtt.MQTTv5
    mqttc = mqtt.Client(client_id = 'hom_server',
                        protocol=mqttv, userdata=userdata,
                        callback_api_version=mqtt.CallbackAPIVersion.VERSION2)
    mqttc.on_message = on_message
    mqttc.on_connect = on_connect
    mqttc.on_disconnect = on_disconnect
    mqttc.on_publish = on_publish
    mqttc.on_subscribe = on_subscribe
    mqttc.on_log = on_log

    if config['mqtt_tls']:
        if not config['mqtt_cacert']:
            logger.info('Specify MQTT_CACERT if self-signed certificate.')
        mqttc.tls_set(ca_certs=config['mqtt_cacert'],
                      certfile=config['mqtt_cert'],
                      keyfile=config['mqtt_key'])
        mqttc.tls_insecure_set(config['mqtt_tls_insecure'])

    try:
        mqttc.connect(config['mqtt_host'],
                      config['mqtt_port'],
                      config['mqtt_timeout'])
        mqttc.loop_start()
        mqttc = mqttc
    except Exception:
        logger.exception(f'Failed to connect to {mqtt_host}')
        sys.exit()

    mqttc.message_callback_add('devices/+/response', message)

    mqttc.subscribe('devices/+/response', mqtt_qos)
    mqttc.subscribe('hom_server/control', mqtt_qos)

    subscriptions = config['mqtt_driver'].get_subscriptions()
    for device in subscriptions.get('data'):
        if device.get('clientid', None) != 'hom_server':
            topic = device.get('topic', None)
            if topic:
                device_name = topic.split('/')[1]
                logger.debug(f'device detected. {device_name}')
                if not device_name in devices:
                    devices[device_name] = {}
                devices[device_name]['status'] = 'online'
                devices[device_name]['timestamp'] = time.time()

    yield {'mqttc': mqttc}

    logger.info('Shutdown...')

    mqttc.loop_stop()
    mqttc.disconnect()
    logger.info('Stop completed')

app = FastAPI(
    title='A simple HTTP REST API proxy for IoT devices behind firewall',
    lifespan=lifespan
)


class ForwardProxyMiddleware(BaseHTTPMiddleware):
    async def dispatch(self, request: Request, call_next):
        path_elm = urllib.parse.urlparse(request.scope['path']).path
        if request.scope['path'] != path_elm:
            request.scope['path'] = path_elm
        request.state.request_id = str(uuid.uuid4())
        response = await call_next(request)
        return response


app.add_middleware(ForwardProxyMiddleware)

app.include_router(commands.router, prefix='/command', tags=['Proxy Commands'])
app.include_router(passthrough.router)


# MQTT handlers
def on_log(mqttc, userdata, level, string):
    if not 'PING' in string or config['verbose']:
        logger.debug(f'on_log(): {userdata} : {level} {string}')

# NOTE(thatsdone): assuming to use MQTTv5
def on_connect(client, userdata, flags, rc, props):
    logger.debug(f'on_connect(): {userdata} : {flags} {rc} {props}')

def on_disconnect(client, userdata, flags, rc, props):
    logger.debug(f'on_disconnect(): {userdata} : {flags} {rc} {props}')

def on_publish(mqttc, userdata, mid, rc, props):
    logger.debug(f'on_publish(): {userdata} : {mid} {rc} {props}')

def on_subscribe(mqttc, userdata, mid, rc, props):
    logger.debug(f'on_subscribe(): {userdata} : {rc} {props}')

def on_message(client, userdata, msg):
    logger.debug(f'on_message(): {userdata} : {msg.topic} {msg.mid} {msg.timestamp} {msg.retain} / {len(msg.payload)}')
    # Note: msg.topic is 'hom_server/control' in this case.

    message = pickle.loads(msg.payload)
    if 'command' in message and 'device' in message:
        logger.debug(message)
        if message['command'] == 'set_status':
            if not message['device'] in devices:
                devices[message['device']] = {}
            devices[message['device']]['status'] = message['status']
            devices[message['device']]['timestamp'] = message['timestamp']

def message(client, userdata, msg):
    logger.debug(f'message(): {userdata} : {msg.topic} {msg.mid} {msg.timestamp} {msg.retain} / binary-msg')

    response = pickle.loads(msg.payload)
    pending_requests[response['request_id']]['response'] = response['response']
    pending_requests[response['request_id']]['status'] = response['status']

    pending_requests[response['request_id']]['event'].set()
