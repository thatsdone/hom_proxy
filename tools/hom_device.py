#!/usr/bin/env python3
# -*- coding: utf-8 -*-
#
# hom_device.py: A stupid simple proxy for servers behind firewalls
#
# Description:
#   hom_device.py connects to a hom_proxy instance actively and
#   forwards HTTP messages from the hom_proxy locally.
#
# License:
#   Apache License, Version 2.0
#
# History:
#   * 2026/08/04 v0.1 Initial version
#
# Author:
#   Masanori Itoh <masanori.itoh@gmail.com>
#
# Dependencies:
#   * paho-mqtt: https://pypi.org/project/paho-mqtt/
#
import sys
import argparse
# common
import paho.mqtt.client as mqtt
# for client
#from paho.mqtt.properties import Properties
#from paho.mqtt.packettypes import PacketTypes

import requests
import urllib
import logging
import socket
import pickle
import time
#
global mqttc
mqttc = None
#
#
#
def on_log(mqttc, userdata, level, string):
    if not 'PING' in string or args.verbose:
        logger.debug('on_log(): %s : %s %s' % (userdata, level, string))

# NOTE(thatsdone): assuming to use MQTTv5
def on_connect(client, userdata, flags, rc, props):
    logger.debug('on_connect(): %s : %s %s %s' % (userdata, flags, rc, props))
    msg = dict()
    msg['command'] = 'set_status'
    msg['device'] = socket.gethostname()
    msg['status'] = 'online'
    msg['timestamp'] = time.time()
    data = pickle.dumps(msg, protocol=pickle.HIGHEST_PROTOCOL)
    mqttc.publish('hom_server/control', args.qos)


def on_disconnect(client, userdata, flags, rc, props):
    logger.debug('on_disconnect(): %s : %s %s %s' % (userdata, flags, rc, props))

def on_publish(client, userdata, mid, rc, props):
    logger.debug('on_publish(): %s : %s %s %s' % (userdata, mid, rc, props))

def on_subscribe(client, userdata, mid, rc, props):
    logger.debug('on_subscribe(): %s : %s %s' % (userdata, rc, props))

def on_message(client, userdata, msg):
    logger.debug('on_message(): %s : %s %s %s %s / %s' % (userdata, msg.topic,
                                                         msg.mid, msg.timestamp,
                                                         msg.retain,
                                                         msg.payload.decode()))
    
# FIXME(thatsdone): Callback API VERSION2 should have 4th argument.
def message(client, userdata, msg):
    logger.debug('message(): %s : %s %s %s %s / %s' % (userdata, msg.topic,
                                                      msg.mid, msg.timestamp,
                                                      msg.retain,
                                                      'binary-msg.'))
    handle_message(msg)

def handle_message(msg):
    logger.debug('handle_message(): %s : %s %s %s / %s' % (msg.topic,
                                                           msg.mid,
                                                           msg.timestamp,
                                                           msg.retain,
                                                           'binnary-msg'))
    data = pickle.loads(msg.payload)
    parsed_url = urllib.parse.urlparse(data['url'])
    request_id = data['request_id']
    # TODO(thatsdone): Consider remote from this device case
    #host = parsed_url.hostname
    host = '127.0.0.1'
    logger.debug('Executing: %s http://%s:%d%s' % (data['method'],
                                                   host,
                                                   parsed_url.port,
                                                   parsed_url.path))

    if not data['method'] in ['GET', 'DELETE']:
        loger.warn('%s not supported (yet)')
        # but passthrough anyway

    response = dict()
    url = 'http://%s:%d%s' % (host, parsed_url.port, parsed_url.path)
    try:
        r = requests.request(data['method'], url,
                             headers=data['headers'], data=None # None for now
                             )
        response['status'] = 0
        response['response'] = r
        response['request_id'] = request_id
        logger.info('"%s %s %s" %s' % (data['method'], data['url'],
                                       data['http_version'], r.status_code))

    except Exception as e:
        logger.error(f'Exception: {e}')
        response['status'] = -1
        response['response'] = None
        response['request_id'] = request_id

    topic = 'devices/%s/response' % (parsed_url.hostname)
    data = pickle.dumps(response, protocol=pickle.HIGHEST_PROTOCOL)
    mqttc.publish(topic, data, args.qos)



if __name__ == "__main__":
    parser = argparse.ArgumentParser(description='hom_device.py')
    parser.add_argument('--debug', action='store_true')
    parser.add_argument('--mqtt_version', type=int, default=5)
    parser.add_argument('--mqtt_host', default=None)
    parser.add_argument('--mqtt_port', type=int, default=1883)
    parser.add_argument('--topic', default=None)
    parser.add_argument('--qos', type=int, default=1)
    parser.add_argument('--timeout', type=int, default=60)
    #parser.add_argument('--tls', action='store_true')
    #parser.add_argument('--cacert', default=None)
    #parser.add_argument('--cert', default=None)
    #parser.add_argument('--key', default=None)
    #parser.add_argument('--tls_secure', action='store_true')
    args = parser.parse_args()
    #
    logger = logging.getLogger('hom_device')
    log_level = "DEBUG" if args.debug else "INFO"
    logger.setLevel(log_level)
    formatter = logging.Formatter(
        fmt = '%(asctime)s.%(msecs)03d %(levelname)s: %(message)s',
        datefmt='%Y/%m/%d %H:%M:%S')
    streamHandler = logging.StreamHandler(sys.stdout)
    streamHandler.setFormatter(formatter)
    logger.addHandler(streamHandler)
    #
    hostname = socket.gethostname().lower()
    topic = 'devices/%s/request' % hostname
    #
    logger.info(f'Using... mqtt_host: {args.mqtt_host} mqtt_port: {args.mqtt_port} mqtt_version: {args.mqtt_version} topic: {topic} qos: {args.qos}')

    if not args.mqtt_host:
        print('Specify at least --host')
        sys.exit()

    userdata = 'server'
    if args.mqtt_version == 3:
        mqttv = mqtt.MQTTv31
    else:
        mqttv = mqtt.MQTTv5

    mqttc = mqtt.Client(client_id=hostname,
                        protocol=mqttv, userdata=userdata,
                        callback_api_version=mqtt.CallbackAPIVersion.VERSION2)
    mqttc.on_message = on_message
    mqttc.on_connect = on_connect
    mqttc.on_disconnect = on_disconnect
    mqttc.on_publish = on_publish
    mqttc.on_subscribe = on_subscribe
    mqttc.on_log = on_log
    mqttc.message_callback_add(topic, message)

    #if args.tls:
    #    if not args.cacert:
    #        print('Specify --cacert')
    #        sys.exit()
    #    mqttc.tls_set(ca_certs=args.cacert,
    #                  certfile=args.cert, keyfile=args.key)
    #    if not args.tls_secure:
    #        mqttc.tls_insecure_set(True)

    mqttc.connect(args.mqtt_host, args.mqtt_port, args.timeout)

    logger.debug('Subscribing to %s' % (topic))
    mqttc.subscribe(topic, args.qos)

    mqttc.loop_forever()
