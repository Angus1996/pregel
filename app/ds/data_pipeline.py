import numpy as np
import tensorflow as tf

from app.ds.graph.np_graph import Graph
from app.utils.constant import TRAIN, LABELS, FEATURES, SUPPORTS, MASK, VALIDATION, TEST, DROPOUT

class DataPipeline():
    '''Class for managing the data pipeline'''

    def __init__(self, model_params, data_dir, dataset_name):
        self.graph = None
        self._populate_graph(model_params, data_dir, dataset_name)
        self.model_params = model_params
        self.num_elements = -1
        self.feature_size = self.graph.features.shape[1]
        self.train_feed_dict = {}
        self.validation_feed_dict = {}
        self.test_feed_dict = {}
        self.placeholder_dict = {}
        self._populate_feed_dicts()

    def _populate_graph(self, model_params, data_dir, dataset_name):
        self.graph = Graph(model_name=model_params.model_name, sparse_features=model_params.sparse_features)
        self.graph.read_data(data_dir=data_dir, datatset_name=dataset_name)
        self.graph.prepare_data(model_params=model_params)

    def _populate_feed_dicts(self, dataset_splits=[1200, 500, 1000]):
        '''Method to populate the feed dicts'''
        dataset_splits_sum = sum(dataset_splits)
        dataset_splits = list(map(lambda x: x / dataset_splits_sum, dataset_splits))

        features = self.graph.features
        labels = self.graph.labels
        supports = self.graph.compute_supports(model_params=self.model_params)

        data_size = self.graph.features.shape[0]
        feature_size = features.shape[1]
        label_size = labels.shape[1]
        support_size = len(supports)
        self.num_elements = 0
        if (self.model_params.sparse_features):
            self.num_elements = features.nnz

        shuffle = np.arange(data_size)
        np.random.shuffle(shuffle)
        features = features[shuffle]
        features = convert_sparse_matrix_to_sparse_tensor(features)

        supports = list(
            map(
                lambda support: convert_sparse_matrix_to_sparse_tensor(support), supports
            )
        )

        labels = labels[shuffle]

        current_index = 0
        train_index = np.arange(current_index, current_index + int(data_size * dataset_splits[0]))
        current_index = int(data_size * dataset_splits[0])
        val_index = np.arange(current_index, current_index + int(data_size * dataset_splits[1]))
        current_index = int(data_size * dataset_splits[1])
        test_index = np.arange(current_index, current_index + int(data_size * dataset_splits[2]))

        self.placeholder_dict = self._placeholder_inputs(feature_size=feature_size,
                                                         label_size=label_size,
                                                         support_size=support_size)

        def get_base_feed_dict():
            feed_dict = {
                self.placeholder_dict[LABELS]: labels,
                self.placeholder_dict[FEATURES]: features
            }
            # Note that supports are not used by the FF model so we might want to put an if conditon here.
            for i in range(len(supports)):
                feed_dict[self.placeholder_dict[SUPPORTS][i]] = supports[i]
            return feed_dict

        self.train_feed_dict = get_base_feed_dict()
        self.train_feed_dict[self.placeholder_dict[MASK]] = map_indices_to_mask(train_index, mask_size=data_size)
        self.train_feed_dict[self.placeholder_dict[DROPOUT]] = self.model_params.dropout

        self.validation_feed_dict = get_base_feed_dict()
        self.validation_feed_dict[self.placeholder_dict[MASK]] = map_indices_to_mask(val_index, mask_size=data_size)
        self.train_feed_dict[self.placeholder_dict[DROPOUT]] = 0.0

        self.test_feed_dict = get_base_feed_dict()
        self.test_feed_dict[self.placeholder_dict[MASK]] = map_indices_to_mask(test_index, mask_size=data_size)
        self.train_feed_dict[self.placeholder_dict[DROPOUT]] = 0.0

    def _placeholder_inputs(self, feature_size, label_size, support_size):
        '''
        Logic borrowed from
        https://github.com/tensorflow/tensorflow/blob/r1.4/tensorflow/examples/tutorials/mnist/fully_connected_feed.py'''

        labels_placeholder = tf.placeholder(tf.int32, shape=(None, label_size), name=LABELS)
        features_placeholder = tf.placeholder(tf.float32, shape=(None, feature_size), name=FEATURES)
        if (self.model_params.sparse_features):
            features_placeholder = tf.sparse_placeholder(tf.float32, shape=(None, feature_size), name=FEATURES)
        mask_placeholder = tf.placeholder(tf.float32, name=MASK)

        # For disabling dropout during testing - based on https://stackoverflow.com/questions/44971349/how-to-turn-off-dropout-for-testing-in-tensorflow
        dropout_placeholder = tf.placeholder_with_default(0.0, shape=(), name=DROPOUT)

        support_placeholder = []

        for i in range(support_size):
            support_placeholder.append(tf.sparse_placeholder(tf.float32, name=SUPPORTS + str(i)))

        return {
            FEATURES: features_placeholder,
            LABELS: labels_placeholder,
            SUPPORTS: support_placeholder,
            MASK: mask_placeholder,
            DROPOUT: dropout_placeholder
        }

    def get_feed_dict(self, mode=TRAIN):
        if mode == TRAIN:
            return self.train_feed_dict
        elif mode == VALIDATION:
            return self.validation_feed_dict
        elif mode == TEST:
            return self.test_feed_dict
        else:
            return None

    def get_placeholder_dict(self):
        '''Method to populate the feed dicts'''
        return self.placeholder_dict


def map_indices_to_mask(indices, mask_size):
    '''Method to map the indices to a mask'''
    mask = np.zeros(mask_size, dtype=np.float32)
    mask[indices] = 1.0
    return mask


def convert_sparse_matrix_to_sparse_tensor(X):
    '''
    code borrowed from https://stackoverflow.com/questions/40896157/scipy-sparse-csr-matrix-to-tensorflow-sparsetensor-mini-batch-gradient-descent
    '''
    coo = X.tocoo()
    indices = np.mat([coo.row, coo.col]).transpose()
    return tf.SparseTensorValue(indices, coo.data, coo.shape)
