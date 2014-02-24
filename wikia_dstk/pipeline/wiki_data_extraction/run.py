import argparse
import os
import random
import sys
from ..config.wiki_data_extraction import config
from boto import connect_s3
from boto.ec2 import connect_to_region
from boto.s3.prefix import Prefix
from boto.utils import get_instance_metadata
from subprocess import Popen, STDOUT
from time import sleep

from config import config

ap = argparse.ArgumentParser()
ap.add_argument('-w', '--wikis', dest='wikis', type=str, default=os.getenv('WIKIS', ''), help='Wiki IDs to run wiki-level data extraction on')
ap.add_argument('-r', '--region', dest='region', type=str, default=config['region'], help='EC2 region to connect to')
args = ap.parse_args()

sys.stdout = os.fdopen(sys.stdout.fileno(), 'w', 0)
BUCKET = connect_s3().get_bucket('nlp-data')

wids = [wid.strip() for wid in args.wikis.split(',')]
print "Working on %d wids" % len(wids)

processes = []
while len(wids) > 0:
    while len(processes) < 8:
        processes.append(Popen('/home/ubuntu/venv/bin/python -m wikia_dstk.pipeline.wiki_data_extraction.child %s' % wids.pop(), shell=True))

    processes = filter(lambda x: x.poll() is None, processes)
    sleep(0.25)

print "Scaling down, shutting down."
current_id = get_instance_metadata()['instance-id']
ec2_conn = connect_to_region(args.region)
ec2_conn.terminate_instances([current_id])
