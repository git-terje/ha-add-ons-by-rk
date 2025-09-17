#!/bin/sh
echo "System dump:" > /data/system_dump.txt
uname -a >> /data/system_dump.txt
df -h >> /data/system_dump.txt
