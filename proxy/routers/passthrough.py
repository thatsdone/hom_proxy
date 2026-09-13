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
import asyncio
import logging
import pickle

from fastapi import APIRouter, HTTPException, Request, Response, status

router = APIRouter()

from shared import pending_requests

logger = logging.getLogger('hom_server')

#async def passthrough(request: Request):
@router.api_route('/', methods=['GET', 'DELETE', 'POST', 'PUT'])
@router.api_route('/{proxy_path:path}', methods=['GET', 'DELETE', 'POST', 'PUT'])
async def passthrough(request: Request, proxy_path: str = ''):
    # TODO: check if the remote target hostname is available,
    #       otherwise return HTTP 502

    request_id = request.state.request_id
    event = asyncio.Event()
    # create a map entry between the event and the request_id above
    pending_requests[request_id] = {
        'event': event,
        'response': None,
    }

    try:
        forward_request = {
            'request_id': request_id,
            'method': request.method,
            'url': str(request.url),
            'http_version': '',
            'headers': '',
            # TODO: set body in case of other method than GET.
            'body': ''
            }
        data = pickle.dumps(forward_request)
        topic = f'devices/{request.url.hostname}/request' 
        request.state.mqttc.publish(topic, data, qos=1)
        try:
            await asyncio.wait_for(event.wait(), timeout=10.0)

            if pending_requests[request_id]['status'] != 0:
                return Response(
                    status_code = status.HTTP_502_BAD_GATEWAY
                )

            return Response(
                status_code=pending_requests[request_id]['response'].status_code,
                headers=pending_requests[request_id]['response'].headers,
                content=pending_requests[request_id]['response'].text
            )
        except Exception:
           logger.exception('Unexpected errror while calling remote server')
           raise HTTPException(
               status_code = status.HTTP_503_SERVICE_UNAVAILABLE,
               detail='Service unavailable'
           )

    finally:
        pending_requests.pop(request_id, None)
