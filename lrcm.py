#!/usr/bin/python3

# lrcm.py - linux remote configuration management agent
#
# Github: https://github.com/72itde/linux-remote-configuration-management
# Developer: https://www.72it.de/#tab-contact
#
# Version: 0.6.0

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
from urllib.parse import urlparse
from ansible.module_utils.parsing.convert_bool import boolean
from jinja2 import Template 
import gc
import resource
import validators
import platform
import distro
import random
from time import sleep
import logging.handlers
import logging_loki
from multiprocessing import Queue


# We get it from distro.name(pretty=True)

LINUX_DISTRIBUTIONS = [
    'Fedora Linux 39 (Workstation Edition)',
    'Debian GNU/Linux 12 (bookworm)',
    'Linux Mint 21.3'
    ]
PYTHON_VERSIONS = [
    '3.10.12',
    '3.11.2',
    '3.12.0'
]

DISTRIBUTION_PRETTY = str(distro.name(pretty=True))
PLATFORM_PYTHON_VERSION = str(platform.python_version())

# enable garbage collection
gc.enable

# functions

def remove_pidfile_and_quit(PIDFILE):
    # remove pidfile
    logging.info("now removing pidfile and exit. Bye.")
    os.remove(PIDFILE)
    del PIDFILE
    exit(0)
    return true

# parse options

parser = OptionParser()
parser.add_option("-c", "--configfile", dest="configfile", default="/etc/lrcm/lrcm.conf", help="custom config file")
parser.add_option("-d", "--debug", action="store_true", dest="debug", default=False, help="run in debug mode")
parser.add_option("-j", "--cronjobs", dest="cronjobs", default=True, help="manage cronjobs")

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

if str(options.cronjobs) == "True":
    logging.info("cronjobs management enabled")
else:
    logging.info("cronjobs management disabled")

# memory logging
def log_memory_usage():
    # On linux, defaults to KB
    memory_usage_kb = resource.getrusage(resource.RUSAGE_SELF).ru_maxrss
    memory_usage_mb = memory_usage_kb / 1024
    logging.debug("memory usage: {:.3f}MB".format(memory_usage_mb))

log_memory_usage()

# read configfile

config = configparser.ConfigParser()
config.read(options.configfile)
DELAY_BEFORE_START_SECONDS = int(config.get('GENERAL', 'delay_before_start_seconds', fallback=60))
DELAY_BEFORE_START_RANDOM_MAX_SECONDS = int(config.get('GENERAL', 'delay_before_start_random_max_seconds', fallback=60))
REPOSITORY = config.get('GIT','repository')
BRANCH = config.get('GIT', 'branch', fallback='main')
PLAYBOOK = config.get('GIT', 'playbook', fallback='playbook.yaml')
AUTHENTICATION_REQUIRED = boolean(config.get('GIT', 'authentication_required', fallback='False'))

logging.debug("authentication required: "+str(AUTHENTICATION_REQUIRED))

if (str(AUTHENTICATION_REQUIRED) == 'True'):
    USERNAME = config.get('GIT', 'username')
    TOKEN = config.get('GIT', 'token')
    o = urlparse(REPOSITORY)
    REPOSITORY_FULL_URL = (o.scheme+"://"+USERNAME+":"+TOKEN+"@"+o.netloc+"/"+o.path)
    logging.debug("full repository url: "+str(REPOSITORY_FULL_URL))
    log_memory_usage()
else:
    REPOSITORY_FULL_URL = REPOSITORY
    logging.debug("full repository url: "+str(REPOSITORY_FULL_URL))
    log_memory_usage()

REBOOT_CRONJOB = config.get('CRONJOB', 'reboot_cronjob', fallback='False')
HOURLY_CRONJOB = config.get('CRONJOB', 'hourly_cronjob', fallback='False')
DAILY_CRONJOB = config.get('CRONJOB', 'daily_cronjob', fallback='False')

PIDFILE = config.get('PIDFILE', 'pidfile', fallback='/run/lrcm.pid')

LOKI_LOGGING_ENABLED = config.get('LOGGING', 'enabled', fallback='False')
LOKI_URL = config.get('LOGGING', 'url', fallback='http://localhost:3100/loki/api/v1/push')
LOKI_AUTHENTICATION_REQUIRED = config.get('LOGGING', 'authentication_required', fallback='False')
LOKI_USERNAME = config.get('LOGGING', 'username', fallback='changeme')
LOKI_PASSWORD = config.get('LOGGING', 'password', fallback='changeme')

# get hostname

myhostname = str(os.uname().nodename)
logging.info("myhostname: "+str(myhostname))

# remote logging to Loki

logging.info("LOKI_LOGGING_ENABLED: "+str(LOKI_LOGGING_ENABLED))


if (LOKI_LOGGING_ENABLED == 'true'):
    logging.info("Loki logging is enabled")
    logger_extra = {"tags": {"service": "lrcm", "hostname": str(myhostname)}}
    handler = logging_loki.LokiHandler(
        url=str(LOKI_URL),
        tags={"hostname": str(myhostname)},
        auth=(str(LOKI_USERNAME), str(LOKI_PASSWORD)),
        version="1",
    )

    logging = logging.getLogger("lrcmlogger")
    logging.addHandler(handler)
    # logging = logging.LoggerAdapter(logging, logger_extra)
    logging.info("Loki logger enabled", extra=logger_extra)

# data type and rule check for config values

# DELAY_BEFORE_START_SECONDS unsigned integer

if (not DELAY_BEFORE_START_SECONDS >= 0):
    logging.error("wrong value for delay_before_start_seconds")
    exit(1)

# DELAY_BEFORE_START_RANDOM_MAX_SECONDS unsigned integer

if (not DELAY_BEFORE_START_RANDOM_MAX_SECONDS >= 0):
    logging.error("wrong value for delay_before_start_random_max_seconds")
    exit(1)


# REPOSITORY url
# BRANCH string
# PLAYBOOK filename
# AUTHENTICATION_REQUIRED boolean
# USERNAME string
# TOKEN string
# REBOOT_CRONJOB boolean
# HOURLY_CRONJOB boolean
# DAILY_CRONJOB boolean
# PIDFILE filename

# check platform support


if (DISTRIBUTION_PRETTY in LINUX_DISTRIBUTIONS):
    logging.info("Distribution "+DISTRIBUTION_PRETTY+" is supported")
else:
    logging.error("Distribution "+DISTRIBUTION_PRETTY+" is not supported")
    exit(1)

if (PLATFORM_PYTHON_VERSION in PYTHON_VERSIONS):
    logging.info("Python version "+PLATFORM_PYTHON_VERSION+" is supported")
else:
    logging.error("Python version "+PLATFORM_PYTHON_VERSION+" is not supported")
    exit(1)

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
    log_memory_usage()
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
        log_memory_usage()
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
        log_memory_usage()
        del mypid
        gc.collect()
    else:
        logging.error("pidfile path "+str(os.path.dirname(PIDFILE))+" is not writable")
        exit(1)


logging.debug("DELAY_BEFORE_START_SECONDS: "+str(DELAY_BEFORE_START_SECONDS))
logging.debug("DELAY_BEFORE_START_RANDOM_MAX_SECONDS: "+str(DELAY_BEFORE_START_RANDOM_MAX_SECONDS))
mysleeptime = (DELAY_BEFORE_START_SECONDS+random.randrange(0, DELAY_BEFORE_START_RANDOM_MAX_SECONDS))
logging.debug("mysleeptime: "+str(mysleeptime))
sleep(mysleeptime)



# create temporary directory

workdir = tempfile.mkdtemp()
logging.info("workdir: "+str(workdir))

# clone repository into workdir

git.Repo.clone_from(REPOSITORY_FULL_URL, workdir, branch=BRANCH, depth=1)

# check if playbook file exists

if (os.access(os.path.dirname(workdir+"/"+PLAYBOOK), os.R_OK)):
    logging.info("playbook "+str(workdir+"/"+PLAYBOOK)+" found")
else:
    logging.error("playbook "+str(workdir+"/"+PLAYBOOK)+" not found")
    remove_pidfile_and_quit(PIDFILE)


# run playbook

def ansible_runner_event_handler(event):
    if (dump := event.get("stdout")):
      logging.info("ansible runner: "+str(dump))
      log_memory_usage()

def run_ansible_runner(PLAYBOOK):
    log_memory_usage()
    ansible_runner_config = ansible_runner.RunnerConfig(private_data_dir=workdir, playbook=PLAYBOOK)
    ansible_runner_config.prepare()
    ansible_runner_config.suppress_ansible_output = True # to avoid ansible_runner's internal stdout dump
    r = ansible_runner.Runner( event_handler=ansible_runner_event_handler, config=ansible_runner_config)
    runner_result = r.run()
    logging.info("runner result: "+str(runner_result))
    del r
    del runner_result
    del ansible_runner_config
    gc.collect()
    log_memory_usage()

run_ansible_runner(PLAYBOOK)



# check if a playbook for this host exists
# debug: copy main playbook to host playbook
# shutil.copyfile(workdir+"/"+PLAYBOOK, workdir+"/"+myhostname+"-"+PLAYBOOK)

if (os.path.isfile(workdir+"/"+myhostname+"-"+PLAYBOOK)):
    logging.info("host-specific playbook found: "+str(workdir+"/"+myhostname+"-"+PLAYBOOK))
    # host-specific playbook run
    run_ansible_runner(PLAYBOOK+"-"+myhostname)
else:
    logging.info("no host-specific playbook found: "+str(workdir+"/"+myhostname+"-"+PLAYBOOK))

def manage_cronjob(special_time, state):
    log_memory_usage()
    # manage cronjobs
    logging.info("manage cronjobs")
    # determine absolute path of this file
    logging.info("script path: "+os.path.abspath(__file__))
    # add some variables
    CRONJOB_SPECIAL_TIME = special_time
    CRONJOB_JOB = os.path.abspath(__file__)+" --configfile="+os.path.abspath(options.configfile)
    # template a playbook file for cronjobs
    File = open(os.path.abspath(os.path.dirname(__file__))+'/templates/cronjob.yaml.j2', 'r')
    content = File.read() 
    File.close() 
    # Render the template and pass the variables 
    template = Template(content) 
    rendered = template.render(CRONJOB_SPECIAL_TIME=CRONJOB_SPECIAL_TIME, CRONJOB_JOB=CRONJOB_JOB, CRONJOB_STATE=CRONJOB_STATE, CRONJOB_FILE_STATE=CRONJOB_FILE_STATE)
    generated_cronjob_playbook_filename = workdir+"/"+"generated_playbook_"+special_time+".yaml"
    output = open(generated_cronjob_playbook_filename, 'w') 
    output.write(rendered) 
    output.close()
    run_ansible_runner(generated_cronjob_playbook_filename)
    del output
    del rendered
    del template
    del File
    del content
    del CRONJOB_JOB
    del CRONJOB_SPECIAL_TIME
    del special_time
    gc.collect()
    log_memory_usage()
    return True


if str(options.cronjobs) == "True":
    if (str(config.get('CRONJOB', 'hourly_cronjob')) == "True" ):
        CRONJOB_STATE = "present"
        CRONJOB_FILE_STATE = "file"
    else:
        CRONJOB_STATE = "absent"
        CRONJOB_FILE_STATE = "absent"
    manage_cronjob("hourly", HOURLY_CRONJOB)
    if (str(config.get('CRONJOB', 'reboot_cronjob')) == "True" ):
        CRONJOB_STATE = "present"
        CRONJOB_FILE_STATE = "file"
    else:
        CRONJOB_STATE = "absent"
        CRONJOB_FILE_STATE = "absent"
    manage_cronjob("reboot", REBOOT_CRONJOB)
    if (str(config.get('CRONJOB', 'daily_cronjob')) == "True" ):
        CRONJOB_STATE = "present"
        CRONJOB_FILE_STATE = "file"
    else:
        CRONJOB_STATE = "absent"
        CRONJOB_FILE_STATE = "absent"
    manage_cronjob("daily", DAILY_CRONJOB)


# remove workdir recursively

shutil.rmtree(workdir)
logging.info("workdir deleted")
logging.error("test for error logging without debug mode")

remove_pidfile_and_quit(PIDFILE)