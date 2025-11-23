#!/bin/bash

docker run -d --name=maxkb --restart=always -p 8080:8080 -v ~/.maxkb_backup:/opt/maxkb 1panel/maxkb
