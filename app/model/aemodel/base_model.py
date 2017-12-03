from app.utils.constant import GCN_AE, SUPPORTS, MODE, TRAIN, NORMALISATION_CONSTANT, LOSS, ACCURACY
from app.model import base_model

from app.layer.GC import SparseGC
from app.layer.IPD import InnerProductDecoder

import tensorflow as tf
import numpy as np

class Base_Model(base_model.Base_Model):
    '''Class for GCN Model'''

    def __init__(self, model_params, sparse_model_params, placeholder_dict, autoencoder_model_params):
        super(Base_Model, self).__init__(model_params=model_params,
                                    sparse_model_params=sparse_model_params,
                                    placeholder_dict=placeholder_dict)
        self.labels = tf.sparse_tensor_to_dense(self.labels)
        # We feed in the adjacency matrix in the sparse format and then make it dense

        # We need the mode variable to know if we need to use the mask values.
        # Since we use almost the entire adjacency matrix at training time, it is inefficient to use a mask
        # parameter at training time.
        self.mode = placeholder_dict[MODE]

        self.supports = placeholder_dict[SUPPORTS]

        self.auc = -1

        self.predictions = None
        self.logits = None

        self.embeddings = None


        # For GCN AE model, the support is just the adj matrix. For clarity, we would save it another param, self.adj
        # We could have set this as one of the params in the AutoEncoderModelParams but are sending it via the
        # placeholderdict to keep it consistent with the base models.
        self.adj = self.supports[0]

        self.normalisation_constant = placeholder_dict[NORMALISATION_CONSTANT]
        self.positive_sample_weight = autoencoder_model_params.positive_sample_weight


    def _loss_op(self):
        '''Operator to compute the loss for the model.
        This method should not be directly called the variables outside the class.
        Not we do not need to initialise the loss as zero for each batch as process the entire data in just one batch.'''

        complete_loss = tf.nn.weighted_cross_entropy_with_logits(
                            targets = self.labels,
                            logits = self.outputs,
                            pos_weight=self.positive_sample_weight
                        )

        def _compute_masked_loss(complete_loss):
            '''Method to compute the masked loss'''
            normalized_mask = self.mask / tf.sparse_reduce_sum(self.mask)
            complete_loss = tf.multiply(complete_loss, tf.sparse_tensor_to_dense(normalized_mask))
            return tf.reduce_sum(complete_loss)
            # the sparse_tensor_to_dense would be the bottleneck step and should be replaced by something more efficient

        complete_loss = tf.cond(tf.equal(self.mode, TRAIN),
                                true_fn=lambda : tf.reduce_mean(complete_loss),
                                false_fn=lambda : _compute_masked_loss(complete_loss))


        return complete_loss * self.normalisation_constant

    def _accuracy_op(self):
        '''Operator to compute the accuracy for the model.
        This method should not be directly called the variables outside the class.'''

        correct_predictions = tf.cast(tf.equal(self.predictions,
                                       self.labels), dtype=tf.float32)

        def _compute_masked_accuracy(correct_predictions):
            '''Method to compute the masked loss'''
            normalized_mask = self.mask / tf.sparse_reduce_sum(self.mask)
            correct_predictions = tf.multiply(correct_predictions, tf.sparse_tensor_to_dense(normalized_mask))
            return tf.reduce_sum(correct_predictions, name="accuracy_op")

        accuracy = tf.cond(tf.equal(self.mode, TRAIN),
                                true_fn=lambda: tf.reduce_mean(correct_predictions, name="accuracy_op"),
                                false_fn=lambda: _compute_masked_accuracy(correct_predictions))

        return accuracy

    def _prediction_op(self):
        '''Operator to compute the predictions from the model'''
        self.logits = tf.sigmoid(x=self.outputs, name="output_to_logits")
        predictions = tf.cast(tf.greater_equal(self.logits, 0.5, name="logits_to_prediction"),
                              dtype=tf.float32)
        return predictions

    def _layers_op(self):
        '''Operator to build the layers for the model.
        This function should not be called by the variables outside the class and
        is to be implemented by all the subclasses'''
        self.layers.append(SparseGC(input_dim=self.input_dim,
                                    output_dim=self.model_params.hidden_layer1_size,
                                    supports=self.supports,
                                    dropout_rate=self.dropout_rate,
                                    activation=tf.nn.relu,
                                    sparse_features=self.model_params.sparse_features,
                                    num_elements=self.num_elements))

        self.layers.append(SparseGC(input_dim=self.model_params.hidden_layer1_size,
                                    # output_dim=int(self.output_shape[1]),
                                    output_dim=self.model_params.hidden_layer2_size,
                                    supports=self.supports,
                                    dropout_rate=self.dropout_rate,
                                    activation=lambda x: x,
                                    sparse_features=False,
                                    num_elements=self.num_elements))

        # So far, we have just added the GCN model.

        self.layers.append(InnerProductDecoder(input_dim=self.input_dim,
                                    output_dim=self.input_dim,
                                    dropout_rate=self.dropout_rate,
                                    activation=lambda x: x,
                                    sparse_features=False))

        # The output of the GCN-AE model is always an adjacency matrix

    def _auc_op(self):
        '''Method to compute the AUC Metric.
        It is not recommended to run this op on CPU as it is very slow.
        A better way to implement this (for test and validation data), would be to use advanced indexing techniques
        similar to numpy which are not yet availabel in tensorflow and can be tracked here:
        https://github.com/tensorflow/tensorflow/issues/206
        Implementing outside the computation graph for now.
        '''


        def _compute_auc_masked():
            labels = self.mask.indices
            return tf.metrics.auc(
                labels=self.labels,
                predictions=tf.sigmoid(self.outputs),
                weights=tf.sparse_tensor_to_dense(self.mask),
                name="auc_op"
            )

        def _compute_auc():
            return tf.metrics.auc(
                labels=self.labels,
                predictions=tf.sigmoid(self.outputs),
                name="auc_op"
            )


        auc = tf.cond(tf.equal(self.mode, TRAIN),
                                true_fn=lambda: _compute_auc(),
                                false_fn=lambda: _compute_auc_masked())

        return auc



    def _compute_metrics(self):
        '''Method to compute the metrics of interest'''
        self.predictions = self._prediction_op()
        self.loss = self._loss_op()
        self.accuracy = self._accuracy_op()
        self.embeddings = self.activations[2]
        tf.summary.scalar(LOSS, self.loss)
        tf.summary.scalar(ACCURACY, self.accuracy)
        self.summary_op = tf.summary.merge_all()