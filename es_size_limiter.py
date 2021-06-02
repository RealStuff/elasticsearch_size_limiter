#!/usr/bin/env python3

# Usage example
# ./es_size_limitter.py --es_host 'https://t-elk01-bfl.intra.realstuff.ch:9200' --es_user elastic --es_pass mysecret --ca_path '/Users/flb/sources/bitbucket.org/realstuff/rs-ansible/files/ssl/CA/intra.realstuff.ch.crt'  --limits '[{"index_pattern":"limiter-test-*","max_size":"10m"}]' --log_level info
# ./es_size_limiter.py --settings settings.yml
#
#

import argparse
import logging
from elasticsearch import Elasticsearch
from ssl import create_default_context
import json
import yaml
import humanfriendly
import sys
import os
import traceback
from collections.abc import Iterable
import uuid
import time

###### Constants 
# Nagio codes
OK       = 0
WARNING  = 1
CRITICAL = 2
UNKNOWN  = 3

###### Classes
# Metrics
# This class is used to store metrics (used for logs and output)
class Metrics:
    status_code = 0
    indices_skipped = 0
    indices_deleted = 0
    bytes_deleted = 0
    index_patterns = []

    def set_status_code(self, status_code):
        if self.status_code < status_code:
            self.status_code == status_code

    def add_indices_skipped(self, count):
        self.indices_skipped += count

    def add_indices_deleted(self, count):
        self.indices_deleted += count

    def add_bytes_deleted(self, count):
        self.indices_deleted += count

    def add_index_pattern(self, pattern):
        self.index_patterns.append(pattern)



###### Functions
# Nagios style exit functions
def exit(status_code, message):
    # Set service name
    service_name = "es_size_limiter"
    # Set status name
    status_name = ""
    if status_code == 0:
        status_name = "OK"
    elif status_code == 1:
        status_name = "Warning"
    elif status_code == 2:
        status_name = "Critical"
    else:
        status_name = "Unknown"

    # Format output and exit
    #message = "{0} {1}: {2}".format(service_name, status_code, message)
    print( "%s %s: %s" % ( service_name, status_name, message ) )
    sys.exit(status_code)

def exit_ok(message):
    exit(OK, message)

def exit_warn(message):
    exit(WARNING, message)

def exit_crit(message):
    exit(CRITICAL, message)

def exit_unknown(message):
    exit(UNKNOWN, message)


# Set logging
def init_logging(settings):

    file_path = settings.get('log_path', '')
    if file_path != "":
        dir_name = os.path.dirname(file_path)

        if not os.path.isdir(dir_name):
            try:
                os.mkdir(dir_name)
            except OSError as err:
                exit_unknown ("Creation of log directory failed: %s" % err)

        # Create file handler
        handler = logging.FileHandler(file_path, mode='a', encoding=None, delay=False)

    else:
        # Create stream handler (stdout)
        handler = logging.StreamHandler()

    # Set log level
    handler.setLevel(getattr(logging, settings.get('log_level').upper()))

    # Create formatter
    formatter = logging.Formatter('%(asctime)s - %(name)s - %(levelname)s - %(message)s')
    handler.setFormatter(formatter)
 
    # Create logger
    logger = logging.getLogger("es_size_limiter")
    logger.setLevel(logging.DEBUG)

    # Add log handlers
    logger.addHandler(handler)

    return logger



# Load settings from file or command line arguments
def load_settings(args):
    # Build absolute file path
    settings = {}

    # First, load settings from file (least significant)
    if (args.settings != None):
        path_settings = args.settings
        if (path_settings.startswith(('/','\\')) == False):
            script_path = os.path.abspath(__file__) #<-- absolute dir the script is in
            script_dir = os.path.split(script_path)[0]
            path_settings = os.path.join(script_dir, path_settings)

        with open(path_settings, 'r') as stream:
            settings = yaml.safe_load(stream)

    # Load settings from command line. Theese settings overwride settings from file
    if (args.es_host != ""):
        settings['es_host'] = args.es_host

    if (args.es_user != ""):
        settings['es_user'] = args.es_user

    if (args.es_pass != ""):
        settings['es_pass'] = args.es_pass

    if (args.es_ca_path != "-"):
        settings['es_ca_path'] = args.es_ca_path

    if (args.log_level != ""):
        settings['log_level'] = args.log_level
    if 'log_level' not in settings:
        settings['log_level'] = "WARNING"

    if (args.log_path != "-"):
        settings['log_path'] = args.log_path

    if (args.limits != ""):
        json_acceptable_string = args.limits.replace("'", "\"")
        limits = json.loads(json_acceptable_string)
        # Convert to list if necessary
        if not isinstance(limits, list):
            limits = [limits]

        settings['limits'] = limits

    return settings


# Setup elasticsearch connection
def es_connect(settings):
    # Validate settings
    if (settings.get('es_host') is None):
        raise ValueError('es_host not configured. Set as commandline option or in settings file')

    if (settings.get('es_user') is None):
        raise ValueError('es_user not configured. Set as commandline option or in settings file')

    if (settings.get('es_pass') is None):
        raise ValueError('es_pass not configured. Set as commandline option or in settings file')

    if (settings.get('es_ca_path') is not None):
        context = create_default_context(cafile=settings['es_ca_path'])
        es = Elasticsearch(
            settings['es_host'],
            http_auth=(settings['es_user'], settings['es_pass']),
            verify_certs=True,
            ssl_show_warn=False,
            ssl_context=context
        )
    else:
        es = Elasticsearch(
            settings['es_host'],
            http_auth=(settings['es_user'], settings['es_pass']),
            verify_certs=False,
            ssl_show_warn=False
        )

    return es



# Limiter function
def limit_size(es, limit, metrics):

    # Get max_size
    max_size = limit.get('max_size',"")
    if (max_size == ""):
        raise ValueError('Missing max_size. Check your configuration')

    max_bytes = humanfriendly.parse_size(max_size)
    total_bytes = 0

    # Check index-pattern (system-indices must not be limitted)
    index_pattern = limit.get('index_pattern', "")
    if (index_pattern == ""):
        raise ValueError('Missing index_pattern. Check your configuration')
    if (index_pattern.startswith('.') and not index_pattern.startswith('.ds') ): # indices starting with . are system indices except .ds which are datastreams
        raise ValueError('Limitting system-incdices not allowed')
    if (index_pattern.startswith('*') and not index_pattern.startswith('.ds') ): # indices starting with . are system indices except .ds which are datastreams
        raise ValueError('Limitting system-incdices not allowed')

    # Set default min_indices
    min_num_indices = limit.get('min_num_indices',1)

    # Get list of indices
    logger.debug("Query indices matching pattern {0}".format(index_pattern))
    
    # Get list of indices
    indices= es.cat.indices(index=index_pattern, format='json', bytes='b', h='index,status,id,docs.count,store.size,creation.date.string', s='creation.date.string')
    if (len(indices) == 0):
        logger.error('{0} - message="No indices found matching pattern {1}", index_pattern="{1}", action="noop" reason="no matching indices", outcome="failure"'.format(trace_id, index_pattern))    
        metrics.set_status_code(CRITICAL)
        return

    logger.debug("Indices found matching pattern {0}".format(index_pattern))
    for index in indices:
        total_bytes += int(index['store.size'])
        logger.debug("  {0}".format(index))
    
    logger.debug("{0} indices found with a total size of {1} Bytes".format(len(indices), humanfriendly.format_size(total_bytes)))

    if (total_bytes > max_bytes):

        logger.debug("Total size of {0} is bigger than max_size of {1}. Action required".format(humanfriendly.format_size(total_bytes),humanfriendly.format_size(max_bytes)))

        # Delete last index
        oldest_index = indices[0]

        # Cirquit-breaker minimum number of incices 
        if (len(indices) <= min_num_indices):
            logger.error('{0} - message="index {1} not deleted", action="skip", reason="min indices reached", outcome="failure", index_name="{1}", index_pattern="{2}", size_total="{3}", size_max="{4}", indices_count={5}, indices_min={6}'.format(trace_id, oldest_index['index'], index_pattern, humanfriendly.format_size(total_bytes), humanfriendly.format_size(max_bytes), len(indices), min_num_indices))
            metrics.set_status_code(CRITICAL)
            metrics.add_indices_skipped(1)
            return
        
        # Catch exception in main function
        #try:
        es.indices.delete(index=oldest_index['index'])
        #except:
        #    logger.error('{0} - message="Delete index {1} failed.", index_pattern="{3}", action="except",  reason="delete-error", exception="{2}"'.format(trace_id, oldest_index['index'], sys.exc_info()[0]))
        metrics.add_indices_deleted(1)
        metrics.add_indices_deleted(int(oldest_index['store.size']))
        logger.warning('{0} - message="index {1} deleted", index_name="{1}", index_size="{2}", index_pattern="{3}", action="delete", reason="limit reached", outcome="success"'.format(trace_id, oldest_index['index'], humanfriendly.format_size(int(oldest_index['store.size'])), index_pattern))
        metrics.set_status_code(WARNING)
        # Maybe size is still too big. Recursively call function again
        limit_size(es, limit, metrics)

    else:
        logger.info('{0} - message="total size is below limit", index_pattern="{1}",  size_total="{2}", size_max="{3}", action="skip", reason="below limit", outcome="success"'.format(trace_id, index_pattern, humanfriendly.format_size(total_bytes),humanfriendly.format_size(max_bytes)))



#### Main ##########################
parser = argparse.ArgumentParser(description='Elasticsearch data size limiter')
parser.add_argument('--es_host', default= "",
                    help='Elasticsearch host. Example: https://t-elk01-bfl.intra.realstuff.ch:9200')
parser.add_argument('--es_user', default= "",
                    help='Elasticsearch username. Example: elastic')
parser.add_argument('--es_pass', default= "",
                    help='Elasticsearch password. Example: mysecret')
parser.add_argument('--es_ca_path', default="-",
                    help='Path to CA cert. If empty, ssl verifications is ignored')
parser.add_argument('--settings', default= "",
                    help='Path to yaml file with limits settings. cmdline arguments have prececence.')
parser.add_argument('--limits', default= "",
                    help='Limit settings in json format. Example \'{"index-pattern":"limiter-test-*","max-size":"10m"}\'')
parser.add_argument('--log_level', default="",
                    help='Log level. One of [DEBUG|INFO|WARNING|ERROR|CRITICAL] (Default: INFO)')
parser.add_argument('--log_path', default="-",
                    help='Path to logfile. If empty, stdout will be used')

args = parser.parse_args()
trace_id = uuid.uuid1()

metrics = Metrics()

try:
    # Load settings
    settings = load_settings(args)
    logger = init_logging(settings)
except Exception as err:
    exit_crit(err)

try:
    # Create elasticsearch connection
    es = es_connect(settings)
    
    # Get limits and make sure they are a list
    limits = settings['limits']
    if not isinstance(limits, list):
        limits = [limits]

    # Run size limitter for all configured limits
    for limit in limits:
        limit_size(es, limit, metrics)
        metrics.add_index_pattern(limit.get('index_pattern'))

except Exception as err:
    logger.critical("message=%s" % err)
    exit_crit(err)
else:
    time.sleep(10 / 1000) # Make sure the timestamp is different than the second last
    logger.info('{0} - message="limiter job finished. Deleted {1} indices with a total size of {2}", num_indices_deleted="{1}", size_total={2}, index_pattern=[{3}] action="exit", reason="limiter job finished", outcome="success"'.format(trace_id, metrics.indices_deleted, humanfriendly.format_size(metrics.bytes_deleted), ','.join(metrics.index_patterns)))
    exit(metrics.status_code, "Limiter job finished. Deleted %d indices with a total size of %s. %d indices skipped. Index-patterns[%s]" % ( metrics.indices_deleted, humanfriendly.format_size(metrics.bytes_deleted), metrics.indices_skipped, ','.join(metrics.index_patterns) ) )
