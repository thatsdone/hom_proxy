#!/usr/bin/env python3
# -*- coding: utf-8 -*-
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
from fastapi import FastAPI, Request
from starlette.middleware.base import BaseHTTPMiddleware
from routers import commands, passthrough
from contextlib import asynccontextmanager
import asyncio

import os
import sys
import logging
import paho.mqtt.client as mqtt
import urllib
import pickle

debug = False
hom_debug = os.getenv('HOM_DEBUG')
if hom_debug and int(hom_debug) != 0:
    debug = True

#
logger = logging.getLogger('hom_server')
log_level = 'DEBUG' if debug else 'INFO'
logger.setLevel(log_level)
formatter = logging.Formatter(
    fmt = '%(asctime)s.%(msecs)03d %(levelname)s: %(message)s',
    datefmt='%Y/%m/%d %H:%M:%S')
streamHandler = logging.StreamHandler(sys.stdout)
streamHandler.setFormatter(formatter)
logger.addHandler(streamHandler)
#
async_loop = None

@asynccontextmanager
async def lifespan(app: FastAPI):
    logger.info('Starting...')

    global async_loop
    async_loop = asyncio.get_running_loop()

    mqtt_version = 5
    mqtt_host = os.getenv('MQTT_HOST')
    if not mqtt_host:
        mqtt_host = '192.168.0.1'
    mqtt_port  = os.getenv('MQTT_PORT')
    if not mqtt_port:
        mqtt_port = 1883
    mqtt_timeout = os.getenv('MQTT_TIMEOUT')
    if not mqtt_timeout:
        mqtt_timeout = 60
    else:
        mqtt_timeout = int(mqtt_timeout)
    mqtt_qos = os.getenv('MQTT_qos')
    if not mqtt_qos:
        mqtt_qos = 1
    else:
        mqtt_qos = int(mqtt_qos)
    
    userdata = 'server'
    if mqtt_version == 3:
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

    tls = False
    
    #if args.tls:
    #    if not args.cacert:
    #        print('Specify --cacert')
    #        sys.exit()
    #    mqttc.tls_set(ca_certs=args.cacert,
    #                  certfile=args.cert, keyfile=args.key)
    #    if not args.tls_secure:
    #        mqttc.tls_insecure_set(True)

    try:
        mqttc.connect(mqtt_host, mqtt_port, mqtt_timeout)
        mqttc.loop_start()
        mqtt_state['mqttc'] = mqttc
    except Exception as e:
        logger.critical('Failed to connect to %s: %s' %(mqtt_host, e))
        sys.exit()

    mqttc.message_callback_add('devices/+/response', message)

    mqttc.subscribe('devices/+/response', mqtt_qos)
    mqttc.subscribe('hom_server/control', mqtt_qos)

    yield {'mqttc': mqttc}

    logger.info('Shutdown...')

    mqtt_state['mqttc'].loop_stop()
    mqtt_state['mqttc'].disconnect()
    logger.info('Stop completed')

app = FastAPI(
    title='A simple HTTP REST API proxy for IoT devices behind firewall',
    lifespan=lifespan
)

import uuid
#
#pending_request = dict()
from shared import pending_requests

class ForwardProxyMiddleware(BaseHTTPMiddleware):
    async def dispatch(self, request: Request, call_next):
        saved_path = request.scope['path']
        path_elm = urllib.parse.urlparse(request.scope['path']).path
        if request.scope['path'] != path_elm:
            request.scope['path'] = path_elm
        request.state.request_id = str(uuid.uuid4())
        response = await call_next(request)
        return response


mqtt_state = {}
app.add_middleware(ForwardProxyMiddleware)

app.include_router(commands.router, prefix='/command', tags=['Proxy Commands'])
app.include_router(passthrough.router)#, tags=['Passthrough Handler'])


#
#
#
def on_log(mqttc, userdata, level, string):
    if not 'PING' in string or args.verbose:
        logger.debug('on_log(): %s : %s %s' % (userdata, level, string))

# NOTE(thatsdone): assuming to use MQTTv5
def on_connect(client, userdata, flags, rc, props):
    logger.debug('on_connect(): %s : %s %s %s' % (userdata, flags, rc, props))

def on_disconnect(client, userdata, flags, rc, props):
    logger.debug('on_disconnect(): %s : %s %s %s' % (userdata, flags, rc, props))

def on_publish(mqttc, userdata, mid, rc, props):
    logger.debug('on_publish(): %s : %s %s %s' % (userdata, mid, rc, props))

def on_subscribe(mqttc, userdata, mid, rc, props):
    logger.debug('on_subscribe(): %s : %s %s' % (userdata, rc, props))

def on_message(client, userdata, msg):
    logger.debug('on_message(): %s : %s %s %s %s / %s' % (userdata, msg.topic,
                                                         msg.mid, msg.timestamp,
                                                         msg.retain,
                                                         len(msg.payload)))

def message(client, userdata, msg):
    logger.debug('message(): %s : %s %s %s %s / %s' % (userdata, msg.topic,
                                                      msg.mid, msg.timestamp,
                                                      msg.retain,
                                                      'binary-msg'))
    response = pickle.loads(msg.payload)
    pending_requests[response['request_id']]['response'] = response['response']
    pending_requests[response['request_id']]['status'] = response['status']
    #
    pending_requests[response['request_id']]['event'].set()
