#!/bin/bash
set -e
mkdir -p /root/.ssh
chmod 700 /root/.ssh
cp /opt/heizung-sonnblick/erich.pub /root/.ssh/authorized_keys
chmod 600 /root/.ssh/authorized_keys
echo OK
