from argparse import ArgumentParser, FileType
from datetime import datetime
from ..loadbalancing import EC2Connection


def get_args():
    ap = ArgumentParser()
    ap.add_argument('--infile', dest="infile", type=FileType('r'))
    ap.add_argument('--s3file', dest='s3file')
    ap.add_argument('--metric', dest="metric", default="cosine")
    ap.add_argument('--slice-size', dest='slice_size', default=500, type=int)
    ap.add_argument('--num-instances', dest='num_instances', type=int, default=10)
    ap.add_argument('--instance-batch-size', dest='instance_batch_size', type=int, default=20000)
    ap.add_argument('--recommendation-name', dest='recommendation_name', default='video')
    ap.add_argument('--num-topics', dest='num_topics', default=999, type=int)
    ap.add_argument('--git-ref', dest='git_ref', default='master')
    return ap.parse_args()


def get_user_data(args, datestamp):
    data = """#!/bin/bash
echo `date` `hostname -i ` "User Data Start" >> /var/log/my_startup.log
mkdir -p /mnt/
cd /home/ubuntu/data-science-toolkit
echo `date` `hostname -i ` "Updating DSTK" >> /var/log/my_startup.log
git fetch origin
git checkout %s
git pull origin %s && sudo python setup.py install
touch /var/log/recommender
python -u -m wikia_dstk.recommendations.server \
--s3file=%s --metric=%s --slice-size=%d \
--use-batches --instance-batch-size=%d --instance-batch-offset=%d
--recommendation-name=%s-%s --num-topics=%d
> /var/log/recommender 2>&1 &
echo `date` `hostname -i ` "User Data End" >> /var/log/my_startup.log
"""
    for i in range(0, len(args.num_instances)):
        yield data % (args.git_ref, args.git_ref, args.s3file, args.metric, args.slice_size,
                      args.instance_batch_size, args.recommendations_name, datestamp, args.num_topics)


def main():
    args = get_args()
    options = dict(price='0.8', ami='ami-4cdcb27c',
                   tag='recommender-%s' % args.recommendation_name)
    conn = EC2Connection(options)
    datestamp = str(datetime.strftime(datetime.now(), '%Y-%m-%d-%H-%M'))
    conn.add_instances_async(8, get_user_data(args, datestamp))
    pass


if __name__ == '__main__':
    main()