# elasticsearch size limiter

Delete Elasticsearch indices based on used storage space.

## What is this repository for?

There is no feature in Elasticsearch to delete indices based on their used space. The only available feature in Elasticsearch is to delete indices based on index creation time. Therefore the es_size_limiter script can be used to limit the total space of indices matching an index-pattern to a configured maximum size. This is how you can prevent full storage, even if you should have massive increase of the log rate.

## How does it work

The script takes a list of limiter settings. A setting contains a index-pattern, a maximum size and optional parameters such as the minimum number of indices to keep.

The script connects to an elasticsearch cluster and does the following steps for each setting in sequence:
- Get the total size of the matching indices.    
  If the total size of the indices is higher than the maximum size and the number of incices is higher than the minimal number of matching indices, the oldest index is deleted.
- Then the procedure is repeated until either the minimal number of indices is reached or the total size is lower than the maximum size.

To simplify the configuration, all commandline parameters can be configured in a yaml file as well. A mix of the two is supported.
When used on both, the commandline parameter takes precedence.

The script can produce detailed logs to protocol each step. Each log contains a trace-id which will change each time the script runs. This is useful to filter out all logs of a given run, e.g. when the logs are loaded to elasticsearch.

The script exits with a nagios compliant commandline output (currently without performance data) and a nagios compliant exit code.


### Configuration options

Please note that mandatory means either configured in cmdline or yaml file

**Setting settings**
| Parameter   | Mandatory     | Default  | Description   |
| :---------- | :------------ | :------- | :------------ |
| es_host     | x             |          | Elasticsearch host (currently only one supported) |
| es_user     | x             |          | Elasticsearch user     |
| es_pass     | x             |          | Elasticsearch password |
| es_ca_path  |               |          | Full path to the elasticsearch CA cert| 
| settings    |               |          | Path to settings yaml file. Can be either absolute or relative. |
| limits      | x             |          | limits in json format. Allowed attributes are described below |
| log_level   |               | warning  | Case insensitive. Allowed values: DEBUG,INFO,WARNING,ERROR,CRITICAL |
| log_path    |               |          | Path to log file: Example: /var/log/es_size_limiter/es_size_limiter.log |
| help        |               |          | Helptext  |

**Limit settings**
| Parameter        | Mandatory     | Default  | Description                                                                             |
| :--------------- | :------------ | :------- | :-------------------------------------------------------------------------------------- |
| index-pattern    | x             |          | The index-pattern to match                                                              |
| max_size         | x             |          | The maximum size of the matching indices in human friendly format, like 10M, 20G, etc.  |
| min_num_indices  |               | 1        | Mimimal number of matching indices to keep. This is mainly used to not break ILM        |

## Examples

### With settings file

```
vim ./settings.yml
# es_size_limitter.py settings file
es_host: https://myserver:9200
es_user: elastic
es_pass: mypass
es_ca_path: /etc/pki/ca-trust/source/anchors/mycacert.pem
log_level: info
log_path: /var/log/es_size_limiter/es_size_limiter.log
# limits contains a list of limit configurations
limits:
- index_pattern: limiter-test-index-foo*
max_size: 10m
#min_num_indices: 1 # Defaults to 1
- index_pattern: limiter-test-index-bar*
max_size: 10m
min_num_indices: 2
```

```
./es_size_limiter.py --settings settings.yml
```


#### With cmdline options

```
./es_size_limitter.py --es_host 'https://myserver:9200' --es_user elastic --es_pass mypass --ca_path '/etc/pki/ca-trust/source/anchors/mycacert.pem'  --limits '[{"index_pattern":"limiter-test-index-foo","max_size":"10m"},{"index_pattern":"limiter-test-index-bar","max_size":"10m","min_num_indices": 2}]' --log_level info --log_path '/var/log/es_size_limiter/es_size_limiter.log'
```

### How do I get set up? ###

1. Install modules
   1. python -m pip install elasticsearch
   2. python -m pip install humanfriendly
   3. python -m pip install pyyaml

2. Run the script

## Additional content

### Scheduled runs

There are many ways to run the script on a schedule, like cron-job, nagios compatible monitoring systems or Logstash (see below).

### Logstash

Logstash can be used to perjodically run the script and load the logs of the script to elasticsearch. An example can be found in the *logstash* directory.

### Elasticsearch

If the logs are loaded to elasticsearch, they can be enriched with a ingest-pipeline. The pipeline config can be found in the *elasticsearch/pipelines* directory.

### Kibana

If the logs produced by the script are ingested to elasticsearch, the ndjson file in the kibana folder can be used to import a index-pattern and a saved search to view and analyse the logs in Kibana.

## Contribution guidelines ###

## Open Issues
- When used with ssl, the script returns a python ssl warning. This is caused by a bug in the elasticsearch python client. As soon as a fix is available it can be solved.

## Who do I talk to? ###
* office@realstuff.ch
