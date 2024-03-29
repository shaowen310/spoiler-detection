# %%
import os
import time
import math
import pickle
from typing import Sequence

import numpy as np
import torch
import sklearn.metrics as metrics

import loggingutil
from dataset import GoodreadsReviewsSpoilerDataset
from model import SpoilerNet
from paramstore import ParamStore

_logger = loggingutil.get_logger('train')
paramstore = ParamStore()
params = {}

# %% [markdown]
# ## Data
# %%
data_dir = 'data_/goodreads-reviews-spoiler'
data_file = os.path.join(data_dir, 'mappings_100000_all_ge5.pkl')
max_sent_len = 15
max_doc_len = 30
batch_size = 32
train_portion, dev_portion = 0.7, 0.1

params['max_sent_len'] = max_sent_len
params['max_doc_len'] = max_doc_len
# %%
# Load
with open(data_file, 'rb') as f:
    data = pickle.load(f)
doc_label_sents = data['doc_label_sents']
doc_df_idf = data['doc_df_idf']
itow = data['itow']
ctoi = data["ctoi"]
doc_key_encode = data['doc_key_encode']
doc_char_encode = data['doc_char_encode']


# %%
# Split train, dev, test
def train_dev_test_split_idx(rand_idx, d: Sequence, n_train: int, n_dev: int):
    d_train = [d[idx] for idx in rand_idx[:n_train]]
    d_dev = [d[idx] for idx in rand_idx[n_train:n_train + n_dev]]
    d_test = [d[idx] for idx in rand_idx[n_train + n_dev:]]
    return d_train, d_dev, d_test


np.random.seed(0)

np.random.seed(0)

n_d = len(doc_label_sents)
n_train = math.floor(n_d * train_portion)
n_dev = math.floor(n_d * dev_portion)
rand_idx = np.random.choice(n_d, n_d, replace=False)

d_train, d_dev, d_test = train_dev_test_split_idx(rand_idx, doc_label_sents, n_train, n_dev)
d_idf_train, d_idf_dev, d_idf_test = train_dev_test_split_idx(rand_idx, doc_df_idf, n_train, n_dev)
d_key_train, d_key_dev, d_key_test = train_dev_test_split_idx(rand_idx, doc_key_encode, n_train,
                                                              n_dev)
d_char_train, d_char_dev, d_char_test = train_dev_test_split_idx(rand_idx, doc_char_encode, n_train,
                                                                 n_dev)

ds_train = GoodreadsReviewsSpoilerDataset(d_train, d_idf_train, d_key_train, itow, max_sent_len,
                                          max_doc_len, ctoi, d_char_train)
ds_dev = GoodreadsReviewsSpoilerDataset(d_dev, d_idf_dev, d_key_dev, itow, max_sent_len,
                                        max_doc_len, ctoi, d_char_dev)
ds_test = GoodreadsReviewsSpoilerDataset(d_test, d_idf_test, d_key_test, itow, max_sent_len,
                                         max_doc_len, ctoi, d_char_test)
dl_train = torch.utils.data.DataLoader(ds_train, batch_size=batch_size, shuffle=True)
dl_dev = torch.utils.data.DataLoader(ds_dev, batch_size=batch_size)
dl_test = torch.utils.data.DataLoader(ds_test, batch_size=batch_size)
# %%
model_name = 'spoilernet'
cell_dim = 128
att_dim = 32
vocab_size = len(itow)
emb_size = 200
use_idf = True
use_char = True
char_vocab_size = len(ctoi)
char_emb_size = 64
char_cell_dim = 32
attent_type = "coAtt"

params['cell_dim'] = cell_dim
params['att_dim'] = att_dim
params['vocab_size'] = vocab_size
params['emb_size'] = emb_size
params['use_idf'] = use_idf
params['use_char'] = use_char
params['char_emb_size'] = char_emb_size
params['char_cell_dim'] = char_cell_dim
params['attent_type'] = attent_type

model_id = paramstore.add(model_name, params)

_logger = loggingutil.get_logger(model_id)

_logger.info('Data file: {}'.format(data_file))

model = SpoilerNet(cell_dim=cell_dim,
                   att_dim=att_dim,
                   vocab_size=vocab_size,
                   emb_size=emb_size,
                   attent_type=attent_type,
                   use_idf=use_idf,
                   char_emb_size=char_emb_size,
                   char_cell_dim=char_cell_dim,
                   use_char=use_char,
                   char_vocab_size=char_vocab_size)
criterion = torch.nn.BCEWithLogitsLoss(reduction='none')

device = torch.device('cuda:1')
model.to(device)
criterion.to(device)

optimizer = torch.optim.Adam(model.parameters())
scheduler = torch.optim.lr_scheduler.StepLR(optimizer, step_size=30, gamma=0.1)


# %% [markdown]
# ## Training
# %%
def train_one_epoch(epoch,
                    model,
                    dataloader,
                    optimizer,
                    criterion,
                    params,
                    device,
                    log_interval=1000):
    model.to(device)
    criterion.to(device)

    model.train()

    epoch_loss = 0
    log_loss = 0
    start_time = time.time()

    for batch, (elems, labels, sentmasks, dfidf, chars, doc_ab) in enumerate(dataloader):
        elems = elems.to(device)
        labels = labels.float().view(-1).to(device)
        sentmasks = sentmasks.view(-1).to(device)
        doc_ab = doc_ab.to(device)

        if params['use_idf']:
            dfidf = dfidf.to(device)
        if params['use_char']:
            chars = chars.to(device)

        optimizer.zero_grad()

        word_h0 = model.init_hidden(len(elems)).to(device)
        sent_h0 = model.init_hidden(len(elems)).to(device)

        if params['use_idf'] and params['use_char']:
            preds, word_h0, sent_h0 = model(elems,
                                            word_h0,
                                            sent_h0,
                                            x_df_idf=dfidf,
                                            chars=chars,
                                            doc_ab=doc_ab)
        elif params['use_char']:
            preds, word_h0, sent_h0 = model(elems, word_h0, sent_h0, chars=chars, doc_ab=doc_ab)
        elif params['use_idf']:
            preds, word_h0, sent_h0 = model(elems, word_h0, sent_h0, x_df_idf=dfidf, doc_ab=doc_ab)
        else:
            preds, word_h0, sent_h0 = model(elems, word_h0, sent_h0, doc_ab=doc_ab)

        loss = criterion(preds, labels)
        loss *= sentmasks
        loss = torch.sum(loss) / torch.count_nonzero(sentmasks)

        loss.backward()
        optimizer.step()

        batch_loss = loss.item()
        epoch_loss += batch_loss
        log_loss += batch_loss

        if log_interval and batch % log_interval == 0 and batch > 0:
            cur_loss = log_loss / log_interval
            elapsed = time.time() - start_time
            print('| epoch {:3d} | {:5d} batches | {:5.2f} ms/batch  | '
                  'loss {:5.2f} | ppl {:8.2f} |'.format(epoch, batch, elapsed * 1000 / log_interval,
                                                        cur_loss, math.exp(cur_loss)))
            log_loss = 0
            start_time = time.time()

    return epoch_loss / len(dataloader)


def f1_score(y_true, y_pred, threshold=0.5):
    y_pred_lb = y_pred >= threshold
    return metrics.f1_score(y_true, y_pred_lb)


def evaluate(model, dataloader, criterion, params, device='cpu'):
    model.to(device)
    criterion.to(device)

    model.eval()

    epoch_loss = 0
    predss = []
    labelss = []
    sentmaskss = []
    with torch.no_grad():
        for elems, labels, sentmasks, dfidf, chars, doc_ab in dataloader:
            elems = elems.to(device)
            labels = labels.float().view(-1).to(device)
            sentmasks = sentmasks.view(-1).to(device)
            doc_ab = doc_ab.to(device)
            if params['use_idf']:
                dfidf = dfidf.to(device)
            if params['use_char']:
                chars = chars.to(device)

            word_h0 = model.init_hidden(len(elems)).to(device)
            sent_h0 = model.init_hidden(len(elems)).to(device)

            if params['use_idf'] and params['use_char']:
                preds, word_h0, sent_h0 = model(elems,
                                                word_h0,
                                                sent_h0,
                                                x_df_idf=dfidf,
                                                chars=chars,
                                                doc_ab=doc_ab)
            elif params['use_char']:
                preds, word_h0, sent_h0 = model(elems, word_h0, sent_h0, chars=chars, doc_ab=doc_ab)
            elif params['use_idf']:
                preds, word_h0, sent_h0 = model(elems,
                                                word_h0,
                                                sent_h0,
                                                x_df_idf=dfidf,
                                                doc_ab=doc_ab)
            else:
                preds, word_h0, sent_h0 = model(elems, word_h0, sent_h0, doc_ab=doc_ab)

            loss = criterion(preds, labels)
            loss *= sentmasks
            loss = torch.sum(loss) / torch.count_nonzero(sentmasks)

            epoch_loss += loss.item()

            labelss.append(labels)
            predss.append(preds)
            sentmaskss.append(sentmasks)

        labels = torch.cat(labelss).detach().cpu().numpy()
        preds = torch.sigmoid(torch.cat(predss).detach()).cpu().numpy()
        sentmasks = torch.cat(sentmaskss).detach().cpu().numpy()
        labels = labels[np.nonzero(sentmasks)]
        preds = preds[np.nonzero(sentmasks)]

        f1 = f1_score(labels, preds, 0.05)
        roc_auc = metrics.roc_auc_score(labels, preds)

    return labels, preds, epoch_loss / len(dataloader), f1, roc_auc


# %%
dev_roc_highest = 0
patience = 3
no_drop_epochs = 0
n_epochs = 50
for epoch in range(n_epochs):
    if no_drop_epochs >= patience:
        break
    epoch_loss = 0

    epoch_loss = train_one_epoch(epoch, model, dl_train, optimizer, criterion, params, device)

    _, _, dev_loss, dev_f1, dev_roc_auc = evaluate(model, dl_dev, criterion, params, device)

    _logger.info(
        '| epoch {} | epoch_loss {:.6f} | dev_loss {:.6f} | dev_f1 {:.3f} | dev_roc_auc {:.3f}'.
        format(epoch, epoch_loss, dev_loss, dev_f1, dev_roc_auc))

    if dev_roc_auc > dev_roc_highest:
        _logger.info("Saving model {}:{}".format(model_id, epoch))
        dev_roc_highest = dev_roc_auc
        torch.save(model.state_dict(), os.path.join('model_', model_id + '.pt'))
        no_drop_epochs = 0
    else:
        no_drop_epochs += 1

# %%
# test
# model_id='spoilernet_5b926d6e'

model.load_state_dict(torch.load(os.path.join('model_', model_id + '.pt')))

dev_label, dev_pred, _, _, _ = evaluate(model, dl_dev, criterion, params, device)

ths = np.arange(0.01, 0.51, 0.01)
dev_f1s = list(map(lambda th: f1_score(dev_label, dev_pred, th), ths))
dev_f1s = np.array(dev_f1s)
max_f1_idx = np.argmax(dev_f1s)

test_label, test_pred, test_loss, test_f1, test_roc_auc = evaluate(model, dl_test, criterion,
                                                                   params, device)

_logger.info('| test_loss {:.6f} | test_f1 {:.3f} | test_roc_auc {:.3f}'.format(
    test_loss, test_f1, test_roc_auc))

test_f1s = list(map(lambda th: f1_score(test_label, test_pred, th), ths))
test_f1s = np.array(test_f1s)

_logger.info('| best_th {:.2f} | best_dev_f1 {:.3f} | best_test_f1 {:.3f} |'.format(
    ths[max_f1_idx], dev_f1s[max_f1_idx], test_f1s[max_f1_idx]))

# %%
