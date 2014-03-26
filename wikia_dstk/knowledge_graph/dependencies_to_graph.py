import requests
from lxml import etree
from neo4jrestclient.client import GraphDatabase
from neo4jrestclient.request import NotFoundError
from argparse import ArgumentParser


def get_args():
    ap = ArgumentParser()
    ap.add_argument(u'-d', u'--exist-db', dest=u'exist_db', default=u'http://nlp-s3:8080')
    ap.add_argument(u'-j', u'--neo4j', dest=u'neo4j', default=u'http://nlp-s3:7474')
    return ap.parse_args()


def get_query(offset=1, limit=500):
    return u"""<query xmlns="http://exist.sourceforge.net/NS/exist" start="%d" max="%d"><text>
xquery version "3.0";
let $documents := collection("/db/nlp/")
for $document in $documents
    for $dependencies in $document//dependencies[@type='collapsed-ccprocessed-dependencies']
        for $dependency in $dependencies
            return &lt;dependencywrapper base-uri="{fn:base-uri($document)}" sentence="{$dependency/../@id}"&gt;
                    {$dependency}
                   &lt;/dependencywrapper&gt;
</text></query>""" % (offset, limit)


def node_from_index(db, index, doc, sentence, word_xml):
    doc_sent_id = doc + u'_' + sentence
    word_id = word_xml.get('idx')
    word = word_xml.text.encode(u'utf8')
    word_nodes = [node for node in index[doc_sent_id][word_id]]
    if not word_nodes:
        word_node = db.nodes.create(word=word, doc=doc, sentence=sentence, word_id=word_id)
        word_node.labels.add(u'Word')
        index[doc_sent_id][word_id] = word_node
    else:
        word_node = word_nodes[0]
    return word_node


def main():
    args = get_args()
    offset = 1
    limit = 500
    db = GraphDatabase(args.neo4j)

    try:
        db.labels.create('Word')
    except:
        pass

    try:
        sentence_index = db.nodes.indexes.get(u'sentence')
    except NotFoundError:
        sentence_index = db.nodes.indexes.create(u'sentence')

    while True:
        r = requests.post(u'%s/exist/rest/db/' % args.exist_db,
                          data=get_query(offset, limit),
                          headers={u'Content-type': u'application/xml'})
        dom = etree.fromstring(r.content)
        for dependencieswrapper in dom:
            doc = dependencieswrapper.get(u'base-uri').split(u'/')[-1].split(u'.')[0]
            sentence = dependencieswrapper.get(u'sentence')
            for dependency in dependencieswrapper[0]:
                try:
                    governor = node_from_index(db, sentence_index, doc, sentence, dependency[0])
                    dependent = node_from_index(db, sentence_index, doc, sentence, dependency[1])
                    db.relationships.create(governor, dependency.get(u'type'), dependent)
                except IndexError:
                    continue

        hits = dom.get('{http://exist.sourceforge.net/NS/exist}hits')
        if not hits:
            print r.content
            break

        if int(hits) <= offset:
            break
        offset += limit


if __name__ == '__main__':
    main()