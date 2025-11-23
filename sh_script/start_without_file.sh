#!/bin/bash

env -u http_proxy -u https_proxy -u HTTP_PROXY -u HTTPS_PROXY -u all_proxy -u ALL_PROXY \
podman run --name maxkb \
    --privileged=true \
    -p 8080:8080 \
    docker.io/1panel/maxkb:latest

