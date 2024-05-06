#!/bin/bash

# Debian 12 deb package build for lrcm

cp ../../lrcm.conf.demo ./lrcm/etc/lrcm/
cp ../../lrcm.py ./lrcm/opt/lrcm/
cp ../../templates/cronjob.yaml.j2 ./lrcm/opt/lrcm/templates/
chmod -R 0700 ./lrcm/opt/ 
chmod 0600 ./lrcm/etc/lrcm/lrcm.conf.demo
chmod 0600 ./lrcm/opt/lrcm/templates/cronjob.yaml.j2
chmod 0700 ./lrcm/opt/lrcm/lrcm.py

dpkg-deb --root-owner-group --build lrcm

rm ./lrcm/etc/lrcm/lrcm.conf.demo
rm ./lrcm/opt/lrcm/lrcm.py
rm ./lrcm/opt/lrcm/templates/cronjob.yaml.j2