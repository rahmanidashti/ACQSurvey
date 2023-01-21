import pandas as pd
from statistics import mean
import os 
import logging
import os
import sys
import re
import random
import numpy as np
import pandas as pd
from datetime import datetime
import nltk
from nltk.stem.porter import PorterStemmer
import numpy as np
import shutil
import pyterrier as pt
pt.init()
from pyterrier.measures import *
from pyterrier_doc2query import Doc2Query
# from pyterrier_t5 import MonoT5ReRanker
# import pyterrier_colbert.ranking

nltk.download('punkt')
nltk.download('stopwords')

np.random.seed(42)
random.seed(42)

logging.basicConfig(
  level=logging.INFO,
  format="%(asctime)s [%(levelname)s] %(message)s",
  handlers=[
      logging.StreamHandler(sys.stdout)
  ]
)

def stem_tokenize(text, remove_stopwords=True):
  stemmer = PorterStemmer()
  tokens = [word for sent in nltk.sent_tokenize(text) \
                                      for word in nltk.word_tokenize(sent)]
  tokens = [word for word in tokens if word not in \
          nltk.corpus.stopwords.words('english')]
  return ' '.join([stemmer.stem(word) for word in tokens])

def keep_alpha(s):
  updated_s = re.sub(r'[^A-Za-z0-9 ]+', '', s)
  return updated_s if len(updated_s) > 0 else 'default'

def document_indexing(data, index_dir):
    data['clean_question'] = data['question'].map(keep_alpha)
    data['tokenized_question'] = data['clean_question'].map(stem_tokenize)
    docs = []
    for index, row in data.iterrows():
        docs.append({'docno':row['question_id'], 'text':row['tokenized_question']})
    
    shutil.rmtree(index_dir)
    iter_indexer = pt.index.IterDictIndexer(index_dir, meta={'docno': 20, 'text': 4096})
    indexref = iter_indexer.index(docs)
    index = pt.IndexFactory.of(indexref)
    return docs, index

def prepare_topics_and_qrels(data):
    # data['query_id'] = data['topic_id'].map(str)
    data['clean_query'] = data['query'].map(keep_alpha)
    data['tokenized_query'] = data['clean_query'].map(stem_tokenize)
    topics = data[['query_id', 'tokenized_query']]
    topics.rename(columns={'query_id': 'qid',
                   'tokenized_query': 'query'},
          inplace=True, errors='raise')
    qrels = data[['query_id', 'question_id']]
    qrels.rename(columns={'query_id': 'qid', 
                'question_id': 'docno'}, inplace=True, errors='raise')
    qrels['label'] = 1
    return topics, qrels

def doc2query_document_indexing(question_docs, index_dir):
    # In this study, we consider each clarification question as a document.
    question_docs['clean_question'] = question_docs['question'].map(keep_alpha)
    question_docs['tokenized_question'] = question_docs['clean_question'].map(stem_tokenize)
    docs = []
    for index, row in question_docs.iterrows():
        # docs.append({'docno':row['qrel'], 'text':row['c_ClarifyingQuestion']})
        if len(row['tokenized_question']) == 0:
            docs.append({'docno':row['question_id'], 'text':"No Clarification."})
        else:
            docs.append({'docno':row['question_id'], 'text':row['tokenized_question']})
    
    shutil.rmtree(index_dir)
    doc2query = Doc2Query(append=True, batch_size=20, num_samples=10) # append generated queries to the orignal document text
    iter_indexer = doc2query >> pt.index.IterDictIndexer(index_dir, meta={'docno': 20, 'text': 4096})
    indexref = iter_indexer.index(docs)
    index = pt.IndexFactory.of(indexref)
    return docs, index


# load data with paired [query, question]
train_data_path = "train.csv"
val_data_path = "val.tsv"
test_data_path = "test.tsv"

train_data_df = pd.read_csv(train_data_path, sep='\t')
val_data_df = pd.read_csv(val_data_path, sep='\t')
test_data_df = pd.read_csv(test_data_path, sep='\t')

train_data_df['query_id'] = train_data_df.index.map(lambda x: 'train_query_'+ str(x))
train_data_df['question_id'] = train_data_df.index.map(lambda x: 'train_question_'+ str(x))
train_data_df['query'] = train_data_df['query'].map(str)
train_data_df['question'] = train_data_df['question'].map(str)

val_data_df['query_id'] = val_data_df.index.map(lambda x: 'val_query_'+ str(x))
val_data_df['question_id'] = val_data_df.index.map(lambda x: 'val_question_'+ str(x))
val_data_df['query'] = val_data_df['query'].map(str)
val_data_df['question'] = val_data_df['question'].map(str)

test_data_df['query_id'] = test_data_df.index.map(lambda x: 'test_query_'+ str(x))
test_data_df['question_id'] = test_data_df.index.map(lambda x: 'test_question_'+ str(x))
test_data_df['query'] = test_data_df['query'].map(str)
test_data_df['question'] = test_data_df['question'].map(str)

full_dataset_dfs = [train_data_df, val_data_df, test_data_df]
full_dataset = pd.concat(full_dataset_dfs) 

topics, qrels = prepare_topics_and_qrels(test_data_df)

print("Indexing the document of clarification questions, ", datetime.now())

!mkdir indexing_dir

index_dir = './indexing_dir'
docs, index = document_indexing(full_dataset, index_dir)

tfidf = pt.BatchRetrieve(index, wmodel="TF_IDF")
BM25 = pt.BatchRetrieve(index, wmodel="BM25")
DPH  = pt.BatchRetrieve(index, wmodel="DPH")
PL2  = pt.BatchRetrieve(index, wmodel="PL2")
DLM  = pt.BatchRetrieve(index, wmodel="DirichletLM")

pt.Experiment(
    [tfidf, BM25, DPH, PL2, DLM],
    topics, 
    qrels,
    eval_metrics=["map", "P_10", "recall_5", "recall_10", "recall_20", "recall_30", "ndcg_cut_20"],
    names=["TF_IDF", "BM25", "DPH", "PL2", "Dirichlet QL"]
)


!mkdir doc2query_index
index_dir = './doc2query_index'
docs, index = doc2query_document_indexing(full_dataset, index_dir)
pt.Experiment([
    pt.BatchRetrieve(index, wmodel="BM25") % 100
  ],
  topics,
  qrels,
  names=["doc2query + BM25"],
  eval_metrics=["map", "P_10", "recall_5", "recall_10", "recall_20", "recall_30", "ndcg_cut_20"],
  verbose = True
)

