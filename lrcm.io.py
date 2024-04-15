#!/usr/bin/python3

# lrcm.io.py - linux remote configuration management agent
#
# Github: https://github.com/72itde/linux-remote-configuration-management
# Developer: https://www.72it.de/#tab-contact
#
# Version: development

#
# imports
#

from optparse import OptionParser
import os
import logging
import sys
import configparser
import tempfile
import shutil
import git
import ansible_runner
import psutil

# parse options

parser = OptionParser()
parser.add_option("-c", "--configfile", dest="configfile", default="/etc/lcrm.io/lcrm.io.conf", help="custom config file")
parser.add_option("-d", "--debug", action="store_true", dest="debug", default=False, help="run in debug mode")
(options, args) = parser.parse_args()

if str(options.debug) == "True":
  logging.basicConfig(stream=sys.stdout, level=logging.DEBUG)

# ----------------------------------------------------------------------
# config check
# ----------------------------------------------------------------------

# check if configfile is readable

if os.access(options.configfile, os.R_OK):
	logging.info("configfile "+options.configfile+" is readable")
else:
	logging.error("configfile "+options.configfile+" is not readable")
	exit(1)

# read configfile

config = configparser.ConfigParser()
config.read(options.configfile)
DELAY_BEFORE_START_SECONDS = config.get('GENERAL', 'delay_before_start_seconds')
REPOSITORY = config.get('GIT','repository')
BRANCH = config.get('GIT', 'branch')
PLAYBOOK = config.get('GIT', 'playbook')
AUTHENTICATION_REQUIRED = config.get('GIT', 'authentication_required')

if (AUTHENTICATION_REQUIRED == True ):
	USERNAME = config.get('GIT', 'username')
	TOKEN = config.get('GIT', 'token')

REBOOT_CRONJOB = config.get('CRONJOB', 'reboot_cronjob')
HOURLY_CRONJOB = config.get('CRONJOB', 'hourly_cronjob')
LOGFILE = config.get('LOGGING', 'logfile')
LOGLEVEL = config.get('LOGGING', 'loglevel')
PIDFILE = config.get('PIDFILE', 'pidfile')

# syntax and rule check for config values


# ----------------------------------------------------------------------
# pidfile management
# ----------------------------------------------------------------------

# check if pidfile already exists

if (os.path.isfile(PIDFILE)):
    logging.warning("pidfile "+PIDFILE+" exists")
    # if exists, compare content to own pid
    mypid = os.getpid()
    logging.info("process id: "+str(mypid))
    pidfile = open(PIDFILE, 'r')
    # Read the first line of the file
    pidinpidfile = pidfile.readline()
    logging.info("pid found in pidfile: "+str(pidinpidfile).strip())
    pidfile.close()
    # ToDo: check if pidinpidfile is an unsigned integer
    # check if process is running for pidinpidfile

    if (psutil.pid_exists(int(pidinpidfile))):
        logging.info("process with pid "+str(pidinpidfile).strip()+" is running. Bye.")
        exit(0)
    else:
        logging.warning("process with pid "+str(pidinpidfile).strip()+" is not running")
        # write my pid to pidfile
        pidfile = open(PIDFILE, 'w')
        pidfile.write(str(mypid))
        pidfile.close()
        logging.info("pid written to pidfile")
else:
    logging.info("pidfile "+PIDFILE+" does not exist")
	# check if pidfile path is writable
    if (os.access(os.path.dirname(PIDFILE), os.W_OK)):
        logging.info("pidfile path "+str(os.path.dirname(PIDFILE))+" is writable")
        mypid = os.getpid()
        logging.info("process id: "+str(mypid))
        pidfile = open(PIDFILE, 'w')
        pidfile.write(str(mypid))
        pidfile.close()
        logging.info("pid written to pidfile")        
    else:
        logging.error("pidfile path "+str(os.path.dirname(PIDFILE))+" is not writable")
        exit(1)



# if different: exit

# if not different: check if the old process is running

# if running: exit

# if not running: update pidfile

# configure logging

# create temporary directory

workdir = tempfile.mkdtemp()
logging.info("workdir: "+str(workdir))

# clone repository into workdir

git.Repo.clone_from(REPOSITORY, workdir, branch=BRANCH, depth=1)

# check if playbook file exists

# run playbook

def ansible_runner_event_handler(event):
    if (dump := event.get("stdout")):
      logging.info("ansible runner: "+str(dump))

ansible_runner_config = ansible_runner.RunnerConfig(private_data_dir=workdir, playbook=PLAYBOOK)
ansible_runner_config.prepare()
ansible_runner_config.suppress_ansible_output = True # to avoid ansible_runner's internal stdout dump

r = ansible_runner.Runner( event_handler=ansible_runner_event_handler, config=ansible_runner_config)

runner_result = r.run()
logging.info("runner result: "+str(runner_result))

# get hostname

myhostname = str(os.uname().nodename)
logging.info("myhostname: "+str(myhostname))

# check if a playbook for this host exists



# remove workdir recursively

shutil.rmtree(workdir)
logging.info("workdir deleted")

# remove pidfile
logging.info("now removing pidfile and exit. Bye.")
os.remove(PIDFILE)
exit(0)