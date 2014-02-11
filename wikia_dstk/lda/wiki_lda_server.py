import time
import warnings
import os
import requests
import argparse
warnings.filterwarnings('ignore', category=DeprecationWarning)
import gensim
from nlp_services.discourse.entities import TopEntitiesService
from nlp_services.syntax import HeadsCountService
from nlp_services.caching import use_caching
from multiprocessing import Pool
from boto import connect_s3
from collections import defaultdict
from . import normalize, unis_bis_tris, launch_lda_nodes, terminate_lda_nodes, harakiri
from . import log, get_dct_and_bow_from_features, write_csv_and_text_data


def get_data(wiki_id):
    use_caching(per_service_cache={'TopEntitiesService.get': {'dont_compute': True},
                                   'HeadsCountService.get': {'dont_compute': True}})
    return [(wiki_id, [sorted(HeadsCountService().get_value(wiki_id).items(), key=lambda y: y[1], reverse=True)[:50],
                       TopEntitiesService().get_value(wiki_id).items()])]


def get_wiki_data_from_api(wiki_ids):
    return requests.get('http://www.wikia.com/api/v1/Wikis/Details', params={'ids': wiki_ids}).json().get('items', {})


def get_args():
    ap = argparse.ArgumentParser(description="Perform latent dirichlet allocation against wiki data")
    ap.add_argument('--num-wikis', dest='num_wikis', type=int,
                    default=os.getenv('NUM_WIKIS', 5000),
                    help="Number of top N wikis to include in learner")
    ap.add_argument('--num-topics', dest='num_topics', type=int,
                    default=os.getenv('NUM_TOPICS', 999),
                    help="Number of topics you want from the LDA process")
    ap.add_argument('--max-topic-frequency', dest='max_topic_frequency', type=int,
                    default=os.getenv('MAX_TOPIC_FREQUENCY', 500),
                    help="Threshold for number of wikis a given topic appears in")
    ap.add_argument('--wamids-file', dest='wamids_file', type=argparse.FileType('r'),
                    default=os.getenv('WAMIDS_FILE', 'topwams.txt'),
                    help="File listing for top WAM wikis by WAM descending")  # I want an API for this, yo
    ap.add_argument('--num-processes', dest="num_processes", type=int,
                    default=os.getenv('NUM_PROCESSES', 8),
                    help="Number of processes for async data access from S3")
    ap.add_argument('--model-prefix', dest='model_prefix', type=str,
                    default=os.getenv('MODEL_PREFIX', time.time()),
                    help="Prefix to uniqueify model")
    ap.add_argument('--path-prefix', dest='path_prefix', type=str,
                    default=os.getenv('PATH_PREFIX', "/mnt/"),
                    help="Prefix to path")
    ap.add_argument('--s3-prefix', dest='s3_prefix', type=str,
                    default=os.getenv('S3_PREFIX', "models/wiki/"),
                    help="Prefix on s3 for model location")
    ap.add_argument('--auto-launch', dest='auto_launch', type=bool,
                    default=os.getenv('AUTOLAUNCH_NODES', True),
                    help="Whether to automatically launch distributed nodes")
    ap.add_argument('--instance-count', dest='instance_count', type=int,
                    default=os.getenv('NODE_INSTANCES', 20),
                    help="Number of node instances to launch")
    ap.add_argument('--node-ami', dest='node_ami', type=str,
                    default=os.getenv('NODE_AMI', "ami-40701570"),
                    help="AMI of the node machines")
    ap.add__argument('--dont-terminate-on-complete', dest='terminate_on_complete', action='store_false',
                     default=os.getenv('TERMINATE_ON_COMPLETE', True),
                     help="Prevent terminating this instance")
    return ap.parse_args()


def get_feature_data(args):
    wids = [str(int(ln)) for ln in args.wamids_file.readlines()][args.num_wikis]

    log("Loading entities and heads...")
    pool = Pool(processes=args.num_processes)
    r = pool.map_async(get_data, wids)
    r.wait()
    entities = dict(r.get())

    log("Getting data from API")
    wids_to_api_data = {}
    widstrings = [','.join(wids[i:i+20]) for i in range(0, len(wids), 20)]
    r = pool.map_async(get_wiki_data_from_api, widstrings, callback=wids_to_api_data.update)
    r.wait()

    wid_to_features = defaultdict(list)
    for wid in entities:
        api_data = wids_to_api_data.get(wid, {})
        for heads_to_count, entities_to_count in entities[wid]:
            wid_to_features[wid] += [word for head, count in heads_to_count for word in [normalize(head)] * count]
            wid_to_features[wid] += [word for entity, count in entities_to_count
                                     for word in [normalize(entity)] * count]
            wid_to_features[wid] += unis_bis_tris(api_data.get('title', ''))
            wid_to_features[wid] += unis_bis_tris(api_data.get('headline', ''))
            wid_to_features[wid] += unis_bis_tris(api_data.get('desc', ''))

    log(len(wid_to_features), "wikis")
    log(len(set([value for values in wid_to_features.values() for value in values])), "features")
    return wid_to_features


def get_model_from_args(args):
    log("\n---LDA Model---")
    modelname = '%d-lda-%swikis-%stopics.model' % (args.model_prefix, args.num_wikis, args.num_topics)
    bucket = connect_s3().get_bucket('nlp-data')
    if os.path.exists(args.path_prefix+modelname):
        log("(loading from file)")
        lda_model = gensim.models.LdaModel.load(args.path_prefix+modelname)
    else:
        log(args.path_prefix+modelname, "does not exist")
        key = bucket.get_key(args.s3_prefix+modelname)
        if key is not None:
            log("(loading from s3)")
            with open('/tmp/%s' % modelname, 'w') as fl:
                key.get_contents_to_file(fl)
            lda_model = gensim.models.LdaModel.load('/tmp/%s' % modelname)
        else:
            log("(building... this will take a while)")
            if args.auto_launch:
                launch_lda_nodes(args.instance_count, args.ami)
            wid_to_features = get_feature_data(args)
            dct, bow_docs = get_dct_and_bow_from_features(wid_to_features)
            lda_model = gensim.models.LdaModel(bow_docs.values(),
                                               num_topics=args.num_topics,
                                               id2word=dict([(x[1], x[0]) for x in dct.token2id.items()]),
                                               distributed=True)
            log("Done, saving model.")
            lda_model.save(args.path_prefix+modelname)
            write_csv_and_text_data(args, bucket, modelname, wid_to_features, bow_docs, lda_model)
            log("uploading model to s3")
            key = bucket.new_key(args.s3_prefix+modelname)
            key.set_contents_from_file(args.path_prefix+modelname)
            terminate_lda_nodes()
    return lda_model


def main():
    args = get_args()
    get_model_from_args(args)
    log("Done")
    if args.terminate_on_complete:
        harakiri()


if __name__ == '__main__':
    main()