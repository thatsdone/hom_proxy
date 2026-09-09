#!/usr/bin/env python3
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
from fastapi import FastAPI
from fastapi import APIRouter, Request, HTTPException, status
import uvicorn

import logging

logger = logging.getLogger(__name__)

app = FastAPI()

router = APIRouter()

methods = ['GET', 'DELETE', 'POST', 'PUT']

@router.api_route('', methods=methods)
def handle_root(request: Request):
    logger.debug(f'handle_root() {request}')
    raise HTTPException(
        status_code=status.HTTP_501_NOT_IMPLEMENTED,
        detail='Not Implemented (yet).'
    )

@router.api_route('/{resource:path}', methods=methods)
def handle_resource(request: Request, resource: str):
    logger.debug(f'handle_resource(): {resource}')
    raise HTTPException(
        status_code=status.HTTP_501_NOT_IMPLEMENTED,
        detail='Not Implemented (yet).'
    )

def run_api_server(host, port):
    logger.debug(f'run_api_server(): {host}:{port}')
    uvicorn.run(app, host=host, port=port)
    raise HTTPException(
        status_code=status.HTTP_501_NOT_IMPLEMENTED,
        detail='Not Implemented (yet).'
    )

app.include_router(router, prefix='/admin')
