#!/bin/bash

# package build for lrcm.io

# Debian 12

cp ../lrcm.io.conf ./lrcm.io/etc/lrcm.io/
cp ../lrcm.io.py ./lrcm.io/opt/lrcm.io/
cp ../templates/cronjob.yaml.j2 ./lrcm.io/opt/lrcm.io/templates/
chmod -R 0700 ./lrcm.io/opt/ 
chmod 0600 ./lrcm.io/etc/lrcm.io/lrcm.io.conf
chmod 0600 ./lrcm.io/opt/lrcm.io/templates/cronjob.yaml.j2
chmod 0700 ./lrcm.io/opt/lrcm.io/lrcm.io.py

dpkg-deb --root-owner-group --build lrcm.io

rm ./lrcm.io/etc/lrcm.io/lrcm.io.conf
rm ./lrcm.io/opt/lrcm.io/lrcm.io.py
rm ./lrcm.io/opt/lrcm.io/templates/cronjob.yaml.j2