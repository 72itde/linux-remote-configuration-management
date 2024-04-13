# linux-remote-configuration-management: lrcm.io

![lrcm.io main image](./lrcm.io.drawio.png)

## main goal

At first we had the need to implement a remote configuration management for some Linux clients
- somewhere in the world
- not accessible
- not always online
- using a secure way
- in a reproducable way
- standardized

We had a first client - a bash-script - running for two years doing all the things we need, but the need for more features brought us here.

## what you get

You get an agent for your favorite Linux distribution in a fully working manner with a configured dummy backend.

## what you can do

You can change the configuration to use your own git instance and develop your own playbooks, roles, etc. You can also use Github as backend. Maybe our commercial offer - a very secure Gitlab instance - is also interesting for you. We're also offering our engineers to develop the playbooks you need for configuration management.

## compatibility matrix

This software will be tested for 100% compatibility on the following operating systems:

- Ubuntu 22.04
- Rocky Linux 9

and maybe also for

- Debian 11 (atm missing package python3-ansible-runner)
- Debian 12
- Ubuntu 20.04
- Rocky Linux 8

## installation

### install dependencies

#### Debian 11

```

```

#### Debian 12

```
```

#### Ubuntu 20.04

```

```

#### Ubuntu 22.04

```
apt-get update
apt-get -y install python3 python3-git python3-ansible-runner
```

#### Ubuntu 24.04

```

```

#### Rocky Linux 8

```

```

#### Rocky Linux 9

```
dnf install git python3-git pip ansible-core
pip3 install GitPython ansible_runner   
```




## testing

### test with demo-repo

```
git clone https://github.com/72itde/linux-remote-configuration-management.git --branch initial-dev
cd linux-remote-configuration-management/
./lrcm.io.py --configfile=lrcm.io.conf --debug
```

## packages

No packages so far.