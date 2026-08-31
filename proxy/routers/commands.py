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
from typing import Dict, List
from fastapi import APIRouter, Request
from pydantic import BaseModel
#
import os
import json
import requests
import base64

from shared import pending_requests

router = APIRouter()

class SubscriptionItem(BaseModel):
    clientid: str
    topic: str
    qos: int

class SubscriptionResponse(BaseModel):
    code: int
    data: List[SubscriptionItem]

# NOTE: This is NanoMQ specific.
@router.get("/subscriptions", response_model=SubscriptionResponse)
def get_subscriptions(request: Request):
    #
    nanomq_host = os.getenv('MQTT_HOST')
    if not nanomq_host:
        nanomq_host = '192.168.0.1'
    nanomq_api_port = 8081
    #
    base_url = 'http://%s:%d/api/v4' % (nanomq_host, nanomq_api_port)
    headers = {}
    token = base64.b64encode(b'admin:public').decode('utf-8')
    headers['Authorization'] = 'Basic %s' % (token)
    url = base_url + '/' + 'subscriptions'
    timeout = 3
    r = requests.get(url, headers=headers, timeout=timeout)
    return json.loads(r.text)


@router.get('/status')
def get_status(request: Request):
    return {'pending_request_count': len(pending_requests.keys())}
