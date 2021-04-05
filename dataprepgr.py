'''
Data credits: Mengting Wan, Rishabh Misra, Ndapa Nakashole, Julian McAuley, "Fine-Grained Spoiler Detection from Large-Scale Review Corpora", in ACL'19.
'''
import collections
import itertools
import functools
import os
import gzip
import json
import pickle

import gdown
from nltk.tokenize import word_tokenize

import loggingutil

# %%
root = 'data_'
base_folder = 'goodreads-reviews-spoiler'
URL = 'https://drive.google.com/uc?id=196W2kDoZXRPjzbTjM6uvTidn6aTpsFnS'
filename = 'goodreads_reviews_spoiler.json.gz'

logger = loggingutil.get_logger('dataprepgr')

# Download
file_dir = os.path.join(root, base_folder)
if not os.path.exists(file_dir):
    os.makedirs(file_dir)
file_path = os.path.join(file_dir, filename)
if not os.path.exists(file_path):
    gdown.download(URL, output=file_path)


# Load
def generate_records(limit=None, log_every=100000):
    count = 0
    with gzip.open(file_path) as fin:
        for l in itertools.islice(fin, limit):
            d = json.loads(l)
            count += 1
            if not (count % log_every):
                logger.debug('Processed {} records'.format(count))
            yield d


def load_records(limit=None):
    return list(generate_records(limit))


# %%
# Reusable
def get_sent_words(sent):
    # tokenize
    words = word_tokenize(sent)
    # transform & filter
    # => lower? stop words? punctuation? HTTP? digits? misspelled?
    return words


def get_label_sent_words(label_sents):
    return [(lb_s[0], get_sent_words(lb_s[1])) for lb_s in label_sents]


def get_word_dict(wc, n_most_common):
    idx2word = ['<pad>', '<unk>']
    idx2word.extend([word for (word, _) in wc.most_common(n_most_common)])
    word2idx = {w: i for i, w in enumerate(idx2word)}
    logger.info("Vocabulary size = {}".format(len(word2idx)))
    return word2idx, idx2word


def get_doc_label_sent_encodes(label_sents, word2idx):
    return [(lb_sw[0], [word2idx[w if w in word2idx else '<unk>'] for w in lb_sw[1]])
            for lb_sw in get_label_sent_words(label_sents)]


# %%
def word_count(records):
    # word frequency
    wc_artwork = collections.defaultdict(lambda: collections.Counter())
    for record in records:
        artwork_id = record['book_id']
        for (_, words) in get_label_sent_words(record['review_sentences']):
            wc_artwork[artwork_id].update(words)
    
    wc = functools.reduce((lambda x, y: x + y), wc_artwork.values(), collections.Counter())

    # vocab
    return wc, wc_artwork


def process(records, word2idx):
    doc_encode = [get_doc_label_sent_encodes(record['review_sentences'], word2idx) for record in records]
    logger.info('Total number of docs: {}', str(len(doc_encode)))
    return doc_encode


def save(obj, filename):
    with open(os.path.join(file_dir, filename + '.pkl'), 'wb') as f:
        pickle.dump(obj, f)


# %%
limit = None
n_most_common = None

wc, wc_artwork = word_count(generate_records(limit))
wtoi, itow = get_word_dict(wc, n_most_common)
doc_encode = process(generate_records(limit), wtoi)
obj = {'doc_label_sents': doc_encode, 'itow': itow, 'wc': wc, 'wc_artwork': wc_artwork}
save(obj, 'mappings_{}_{}'.format('all' if limit is None else str(limit), 'all' if n_most_common is None else str(n_most_common)))

# %%
