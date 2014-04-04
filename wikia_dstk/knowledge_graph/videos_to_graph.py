from neo4jrestclient.client import GraphDatabase
from argparse import ArgumentParser
from multiprocessing import Pool
import traceback
import requests


def get_args():
    ap = ArgumentParser()
    ap.add_argument(u'--graph-db', dest=u'graph_db', default=u'http://nlp-s3:7474/')
    ap.add_argument(u'--solr', dest=u'solr', default=u'http://search-s10:8983/solr/main')
    ap.add_argument(u'--num-processes', dest=u'num_processes', type=int, default=8)
    return ap.parse_args()


def escape_value(string):
    return string.replace(u"'", u"\\'")


def handle_doc(tup):
    try:
        args, doc = tup
        db = GraphDatabase(args.graph_db)
        if u'title_en' not in doc:
            return
        name = doc[u'title_en'].replace(u'"', u'').lower()
        print name.encode(u'utf8')
        actor_index = db.nodes.indexes.get(u'actor')
        wid = doc[u'wid']
        video_node = db.nodes.create(doc_id=doc[u'id'], name=name.encode(u'utf8'))
        video_node.labels.add(u'Video')

        for actor in doc[u'video_actors_txt']:
            actor_node = db.nodes.create(name=actor)
            if u"Actor" not in actor_node.labels:
                actor_node.labels.add(u'Actor')
            actor_index[wid][actor] = actor_node

            try:
                db.relationships.create(video_node, u'stars', actor_node)
                db.relationships.create(actor_node, u'acts_in', video_node)
            except Exception as e:
                print e
    except Exception as e:
        print e
        traceback.format_exc()
        raise e


def run_queries(args, pool, start=0):
    query_params = dict(q=u'is_video:true AND video_actors_txt:*', fl=u'id,title_en,video_actors_txt,wid',
                        wt=u'json', start=start, rows=500)
    while True:
        response = requests.get(u'%s/select' % args.solr, params=query_params).json()
        map(handle_doc, [(args, doc) for doc in response[u'response'][u'docs']])
        if response[u'response'][u'numFound'] <= query_params[u'start']:
            return True
        query_params['start'] += query_params['rows']


def main():
    args = get_args()
    db = GraphDatabase(args.graph_db)
    try:
        actor_index = db.nodes.indexes.create(u'actor')
    except Exception as e:
        print e
    for label in [u'Video', u'Actor']:
        try:
            db.labels.create(label)
        except:
            continue
    #pool = Pool(processes=args.num_processes)
    pool = False
    run_queries(args, pool)


if __name__ == '__main__':
    main()