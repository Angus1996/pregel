import os
from abc import ABC, abstractmethod

import numpy as np
from scipy import sparse as sp
from scipy.sparse.linalg.eigen.arpack import eigsh

from app.utils.constant import GCN, NETWORK, LABEL, FEATURE,SYMMETRIC, GCN_POLY
from app.utils.util import invert_dict, map_set_to_khot_vector, map_list_to_floats


class Base_Graph(ABC):
    '''Base class for the graph data structure'''

    def __init__(self, model_name=GCN, sparse_features=True):
        '''Method to initialise the graph'''
        self.preprocessed = False
        self.features = None
        # nodes X features
        self.adj = None
        self.labels = None
        # nodes X labels

        # For optimisation
        self.sparse_features = sparse_features

        # We are saving the model_name as different models would need different kind of preprocessing.
        self.model_name = model_name

        # We are saving the mappings so that we do not have to make any assumptions about the data types any more.
        # `label` and `node` are assumed to be strings as read from the input file.
        self.label_to_id_map = {}
        self.id_to_label_map = {}
        self.node_to_id_map = {}
        self.id_to_node_map = {}

        # Mapping of node to labels and lables to nodes. We would use the latter for computing scores.
        # Note that these ds are using the ids and not the raw strings read from the file.
        self.label_to_node_map = {}
        self.node_to_label_map = {}

        self.edge_count = -1

    def read_labels(self, label_data_path):
        '''
        Method to read the lables from `data_path`
        '''
        print("Reading labels from", str(label_data_path))
        data = np.genfromtxt(label_data_path, dtype=np.dtype(str))

        label_to_id_map = {label: id for id, label in enumerate(
            set(
                list(
                    map(lambda _data: _data[1], data)
                )
            )
        )}

        node_to_id_map = {node: id for id, node in enumerate(
            set(
                list(
                    map(lambda _data: _data[0], data)
                )
            )
        )}

        node_to_label_map = {}
        label_to_node_map = {}

        for node, label in map(lambda _data: (node_to_id_map[_data[0]], label_to_id_map[_data[1]]), data):
            if node not in node_to_label_map:
                node_to_label_map[node] = set()
            node_to_label_map[node].add(label)
            if label not in label_to_node_map:
                label_to_node_map[label] = set()
            label_to_node_map[label].add(node)

        label_count = len(label_to_id_map.keys())

        labels = np.asarray(list(
            map(lambda index_set: map_set_to_khot_vector(index_set=index_set, num_classes=label_count)
                , node_to_label_map.values())
        ))

        assert (len(self.id_to_node_map.keys()) == len(self.node_to_label_map.keys())), \
            "Some nodes are missing labels or ids"

        assert (len(self.id_to_label_map.keys()) == len(self.label_to_node_map.keys())), \
            "Some labels are missing nodes or ids"

        node_count = labels.shape[0]
        label_count = labels.shape[1]

        # Updating all the class variables in one place
        self.label_to_id_map = label_to_id_map
        self.node_to_id_map = node_to_id_map
        self.node_to_label_map = node_to_label_map
        self.label_to_node_map = label_to_node_map

        self.id_to_label_map, self.id_to_node_map = list(
            map(lambda _dict: invert_dict(_dict), [
                label_to_id_map, node_to_id_map
            ])
        )

        self.labels = labels

        print("{} nodes read.".format(node_count))
        print("{} labels read.".format(label_count))

    def read_features(self, feature_data_path, one_hot=False, dim=100):
        '''
        Method to read the features from `feature_data_path`
        '''
        # Check if the `feature_data_path` is set else generate default feature vectors

        node_count = len(self.id_to_node_map.keys())

        if (feature_data_path):
            features = np.genfromtxt(feature_data_path, dtype=np.dtype(str))
            features = np.asarray(
                list(map(map_list_to_floats, features[:, 1:])), dtype=np.int32)
            if self.sparse_features:
                features = sp.csr_matrix(features)

        else:
            if (one_hot):
                # In case of one_hot features, we ignore the set value of `dim` and use dim = node_count.
                dim = node_count
                assert (dim > 0), "node count  = ".format(dim)
                if self.sparse_features:
                    features = sp.identity(dim).tocsr()
                else:
                    features = sp.identity(dim).todense()
            else:
                features = np.random.uniform(low=0, high=0.5, size=(node_count, dim))

        assert (features.shape[0] == node_count), "Missing features for some nodes"
        self.features = features
        print("{} features read for each node.".format(self.features.shape[1]))

    def read_data(self, data_dir=None, dataset_name=None):
        '''
        Method to read the data corresponding to `dataset_name` from `data_dir`

        :return:
        Populates self.features, self.adjacency_matrix, self.labels
        '''
        data_path = os.path.join(data_dir, dataset_name)
        print("Reading data from", str(data_path))

        data_path_map = {}
        data_path_map[NETWORK] = os.path.join(data_path, "network.txt")
        data_path_map[LABEL] = os.path.join(data_path, "label.txt")
        data_path_map[FEATURE] = os.path.join(data_path, "feature.txt")

        self.read_labels(label_data_path=data_path_map[LABEL])
        self.read_features(feature_data_path=data_path_map[FEATURE])
        self.read_network(network_data_path=data_path_map[NETWORK])

    @abstractmethod
    def read_network(self, network_data_path):
        '''
        Method to read the network from `network_data_path`
        '''
        pass

    def compute_supports(self, model_params):
        '''
        Method to compute the supports for the graph before feeding to the model
        '''

        adj = self.adj
        if(model_params.model_name==GCN_POLY):
            supports = compute_chebyshev_polynomial(adj, degree=model_params.support_size - 1)

        else:
            supports = [transform_adj(adj=adj, is_symmetric=True)]
        return supports

def symmetic_adj(adj):
    '''
    Method to preprocess the adjacency matrix `adj`
    :return: symmetric adjacency matrix

    Let us say the input matrix was [[1, 2]
                                    [1, 1]]
    To make it symmetric, we compute the max of the values at  index pairs (i, j) and (j, i) and set both (i, j) and
    (j, i) to that value.
    '''

    adj_t = adj.T
    return adj + adj_t.multiply(adj_t > adj) - adj.multiply(adj_t > adj)

def transform_adj(adj, is_symmetric=True):
    '''
    Method to transform the  adjacency matrix as described in section 2 of https://arxiv.org/abs/1609.02907
    '''
    adj = adj + sp.eye(adj.shape[0])
    # Adding self connections

    adj = renormalization_trick(adj, is_symmetric)

    return adj

def renormalization_trick(adj, symmetric=True):
    if symmetric:
        # dii = sum_j(aij)
        # dii = dii ** -o.5
        d = sp.diags(
            np.power(np.asarray(adj.sum(1)), -0.5).flatten(),
            offsets=0)
        # dii . adj . dii
        return adj.dot(d).transpose().dot(d).tocsr()

def get_identity(size):
    '''return indentity matrix of the given size'''
    return sp.eye(m=size)

def compute_chebyshev_polynomial(adj, degree):
    '''Method to compute Chebyshev Polynomial upto degree `degree`'''

    adj_normalized = renormalization_trick(adj=adj)

    identity_size  = adj.shape[0]

    # laplacian_normalized = In - adj_normalized
    laplacian_normalized = get_identity(identity_size) - adj_normalized
    eigval, _ = eigsh(A = laplacian_normalized, k = 1, which="LM")

    # L = 2L/lamba_max - In
    laplacian_normalized_scaled = (2.0 * laplacian_normalized)/eigval[0] - get_identity(identity_size)
    Tk = [get_identity(identity_size), laplacian_normalized_scaled]
    # Tk = [Tk[-1] + Tk[-2]]

    for i in range(2, degree+1):
        Tk.append(_compute_chebyshev_recurrence(current = Tk[-1],
                                               previous = Tk[-2],
                                               X = laplacian_normalized_scaled))
    return Tk

def _compute_chebyshev_recurrence(current, previous, X):
    '''Method to compute the next term of the Chebyshev recurrence'''

    next = 2 * X.dot(current) - previous
    return next
