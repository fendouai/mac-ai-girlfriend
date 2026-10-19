"""Acceptance-test hook: reject public network access in this Python process only."""
import ipaddress
import socket
import sys
from urllib.parse import urlsplit


def local(host):
    if host in (None, '', 'localhost'):
        return True
    try:
        address = ipaddress.ip_address(host)
        return address.is_private or address.is_loopback
    except ValueError:
        return False


def check_url(url):
    if not local(urlsplit(str(url)).hostname):
        raise RuntimeError('Offline verification blocked public URL: ' + str(url))


original_dns = socket.getaddrinfo

def guarded_dns(host, *args, **kwargs):
    if not local(host):
        raise RuntimeError('Offline verification blocked public host: ' + str(host))
    return original_dns(host, *args, **kwargs)

socket.getaddrinfo = guarded_dns

import requests
original_send = requests.Session.send

def send(self, request, *args, **kwargs):
    check_url(request.url)
    return original_send(self, request, *args, **kwargs)

requests.Session.send = send

import httpx
original_httpx = httpx.Client.send
original_async = httpx.AsyncClient.send

def httpx_send(self, request, *args, **kwargs):
    check_url(request.url)
    return original_httpx(self, request, *args, **kwargs)

async def httpx_async(self, request, *args, **kwargs):
    check_url(request.url)
    return await original_async(self, request, *args, **kwargs)

httpx.Client.send = httpx_send
httpx.AsyncClient.send = httpx_async
print('Offline verification: public DNS / HTTP requests are blocked', file=sys.stderr, flush=True)
