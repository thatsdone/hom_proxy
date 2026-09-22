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
import base64
import json
import logging
import os

import requests
from fastapi import APIRouter, Request
from pydantic import BaseModel

from shared import config, devices, pending_requests

logger = logging.getLogger('hom_server')
router = APIRouter()

class SubscriptionItem(BaseModel):
    clientid: str
    topic: str
    qos: int

class SubscriptionResponse(BaseModel):
    code: int
    data: list[SubscriptionItem]

@router.get("/subscriptions", response_model=SubscriptionResponse)
def get_subscriptions(request: Request):

    res = config['mqtt_driver'].get_subscriptions()

    return res

@router.get('/status')
def get_status(request: Request):
    res = {
        'pending_request_count': len(pending_requests.keys())
    }
    logger.debug(f'devices: {devices}')
    res['devices'] = []
    for device in devices.keys():
        logger.debug(type(device))
        res['devices'].append({'hostname': device,
                               'status': devices[device]['status'],
                               'timestamp': devices[device]['timestamp']
                               })
    return res
