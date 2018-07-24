# !/usr/bin/env python
# -*- coding:utf-8 -*-

import pandas as pd
import numpy as np
import tensorflow as tf
from sklearn.preprocessing import LabelEncoder, MinMaxScaler
from sklearn.metrics import roc_auc_score, accuracy_score, log_loss, mean_squared_error
import time
import warnings
warnings.filterwarnings('ignore')
from DataParse import DataParse

class Wide_Deep:
    def __init__(self, continuous_feature, category_feature, cross_feature=[], ignore_feature=[], category_dict={},
                 category_size=0, category_field_size=0, embedding_size=8, deep_layers=[32, 32], dropout_deep=[0.5, 0.5, 0.5],
                 deep_layers_activation=tf.nn.relu, epochs=10, batch_size=128,learning_rate=0.001, optimizer_type='adam',
                 random_seed=2018, loss_type='logloss', metric_type='auc', l2_reg=0.0, use_wide=True, use_deep=True):
        self.continuous_feature = continuous_feature
        self.category_feature = category_feature
        self.cross_feature = cross_feature
        self.ignore_feature = ignore_feature
        self.category_dict = category_dict
        self.category_size = category_size
        self.category_field_size = category_field_size
        self.embedding_size = embedding_size
        self.deep_layers = deep_layers
        self.dropout_deep = dropout_deep
        self.deep_layers_activation = deep_layers_activation
        self.epochs = epochs
        self.batch_size = batch_size
        self.learning_rate = learning_rate
        self.optimizer_type = optimizer_type
        self.random_seed = random_seed
        self.loss_type = loss_type
        self.metric_type = metric_type
        self.l2_reg = l2_reg
        self.use_wide = use_wide
        self.use_deep = use_deep

    def get_cross_feature(self, df):
        '''
        cross_feature格式：[['a', 'b'], ['c', 'd']]，表示a与b交叉，c与d交叉
        cross_name: ['a_b', 'c_d']
        '''

        if len(self.cross_feature) == 0:
            return
        cross_name = ['_'.join(col) for col in self.cross_feature]

        crossed_columns = {}

        for name, cross in zip(cross_name, self.cross_feature):
            crossed_columns[name] = cross

        print(crossed_columns)

        df_cross = pd.DataFrame()
        for k, v in crossed_columns.items():
            df_cross[k] = df[v].astype(str).apply(lambda x: '-'.join(x), axis=1)

        lbc = LabelEncoder()
        print('start label encoder')
        for col in cross_name:
            print('this feature is', col)
            try:
                df_cross[col] = lbc.fit_transform(df_cross[col].apply(int))
            except:
                df_cross[col] = lbc.fit_transform(df_cross[col].astype(str))
        return df_cross

    def fit(self, category_index, train, label):
        self.graph = tf.Graph()
        with self.graph.as_default():
            tf.set_random_seed(self.random_seed)

            self.wide_feature_size = len(self.continuous_feature) + len(self.category_feature) + len(self.cross_feature)
            self.deep_feature_size = len(self.continuous_feature) + len(self.category_feature)

            self.cate_index = tf.placeholder(tf.int32, [None, self.category_field_size], name='category_index')
            self.cont_feats = tf.placeholder(tf.float32, [None, len(self.continuous_feature)], name='continuous_feature')
            self.wide_input = tf.placeholder(tf.float32, [None, self.wide_feature_size], name='wide_data')
            self.deep_input = tf.placeholder(tf.float32, [None, self.deep_feature_size], name='deep_data')
            self.label = tf.placeholder(tf.float32, [None, 1], name='label')

            weights = {}
            biases = {}

            with tf.name_scope('wide_part'):
                if len(self.cross_feature) > 0:
                    cross = self.get_cross_feature(train)
                    wide_data = pd.concat([train, cross], axis=1)
                else:
                    wide_data = train

                weights['wide_w'] = tf.Variable(tf.random_normal([self.wide_feature_size, 1]))
                biases['wide_b'] = tf.Variable(tf.random_normal([1]))

                if  self.use_wide and self.use_deep == False:
                    self.wide_out = tf.add(tf.matmul(self.wide_input, weights['wide_w']), biases['wide_b'])
                else:
                    self.wide_out = self.wide_input

            with tf.name_scope('deep_part'):
                num_layer = len(self.deep_layers)
                weights['category_embedding'] = tf.Variable(tf.random_normal([self.category_size, self.embedding_size], mean=0.0, stddev=0.01))

                # category -> Embedding
                self.embedding = tf.nn.embedding_lookup(weights['category_embedding'], ids=self.cate_index)  # [None, category_field_size, embedding_size]
                self.embedding = tf.reshape(self.embedding, shape=[-1, self.category_field_size * self.embedding_size])  # [None, category_field_size * embedding_size]
                # concat Embedding Vector & continuous -> Dense Vector
                self.dense_vector = tf.concat([self.embedding, self.cont_feats], axis=1) # [None, self.category_field_size * self.embedding_size + cont_feats_size]

                input_size = self.dense_vector.shape.as_list()[1]
                glorot = np.sqrt(2.0 / (input_size + self.deep_layers[0]))
                weights['deep_layer_0'] = tf.Variable(
                    np.random.normal(loc=0, scale=glorot, size=(input_size, self.deep_layers[0])),
                    dtype=np.float32)
                biases['deep_layer_bias_0'] = tf.Variable(np.random.normal(loc=0, scale=glorot, size=(1, self.deep_layers[0])),
                                                          dtype=np.float32)

                for i in range(1, num_layer):
                    glorot = np.sqrt(2.0 / (self.deep_layers[i - 1] + self.deep_layers[i]))
                    weights['deep_layer_%s' % i] = tf.Variable(
                        np.random.normal(loc=0, scale=glorot, size=(self.deep_layers[i - 1], self.deep_layers[i])),
                        dtype=np.float32)
                    biases['deep_layer_bias_%s' % i] = tf.Variable(
                        np.random.normal(loc=0, scale=glorot, size=(1, self.deep_layers[i])),
                        dtype=np.float32)

                self.deep_out = tf.add(tf.matmul(self.dense_vector, weights['deep_layer_0']), biases['deep_layer_bias_0'])
                self.deep_out = tf.nn.relu(self.deep_out)

                for i in range(1, num_layer):
                    self.deep_out = tf.add(tf.matmul(self.deep_out, weights['deep_layer_%s' % i]), biases['deep_layer_bias_%s' % i])
                    self.deep_out = tf.nn.relu(self.deep_out)

                if self.use_deep and self.use_wide == False:
                    glorot = np.sqrt(2.0 / (self.deep_layers[-1] + 1))
                    weights['deep_out'] = tf.Variable(np.random.normal(loc=0, scale=glorot, size=(self.deep_layers[-1] , 1)),
                                                      dtype=np.float32)
                    biases['deep_out_bias'] = tf.Variable(np.random.normal(loc=0, scale=glorot, size=(1, 1)),
                                                          dtype=np.float32)
                    self.deep_out = tf.add(tf.matmul(self.deep_out, weights['deep_out']), biases['deep_out_bias'])

                # self.deep_out = tf.keras.layers.Dense(self.deep_layers[0], activation=self.deep_layers_activation)(self.dense_vector)
                # for i in range(1, num_layer):
                #     self.deep_out = tf.keras.layers.Dense(self.deep_layers[i], activation=self.deep_layers_activation)(self.deep_out)

                if self.use_deep and self.use_wide == False:
                    self.deep_out = tf.keras.layers.Dense(1, activation=None)(self.deep_out)

            with tf.name_scope('wide_deep'):
                if self.use_wide and self.use_deep:
                    input_size = self.wide_feature_size + self.deep_layers[-1]

                    glorot = np.sqrt(2.0 / (input_size + 1))
                    weights['concat_projection'] = tf.Variable(np.random.normal(loc=0, scale=glorot, size=(input_size, 1)), dtype=np.float32)
                    biases['concat_bias'] = tf.Variable(tf.constant(0.01), dtype=np.float32)
                    concat_input = tf.concat([self.wide_out, self.deep_out], axis=1)
                    self.out = tf.add(tf.matmul(concat_input, weights['concat_projection']), biases['concat_bias'])
                elif self.use_wide:
                    self.out = self.wide_out
                elif self.use_deep:
                    self.out = self.deep_out

            # loss
            if self.loss_type == 'logloss':
                self.out = tf.nn.sigmoid(self.out)
                self.loss = tf.losses.log_loss(self.label, self.out)

            elif self.loss_type == 'mse':
                self.loss = tf.nn.l2_loss(tf.subtract(self.label, self.out))

            # l2 regularization on weights
            if self.l2_reg > 0:
                if self.use_deep:
                    for i in range(len(self.deep_layers)):
                        self.loss = self.loss + self.l2_reg * (
                                    tf.nn.l2_loss(weights['deep_layer_%s' % i]) + tf.nn.l2_loss(biases['deep_layer_bias_%s' % i]))

            # optimizer
            if self.optimizer_type == 'adam':
                self.optimizer = tf.train.AdamOptimizer(learning_rate=self.learning_rate).minimize(self.loss)

            elif self.optimizer_type == 'adagrad':
                self.optimizer = tf.train.AdagradOptimizer(learning_rate=self.learning_rate,
                                                           initial_accumulator_value=1e-8).minimize(self.loss)

            elif self.optimizer_type == 'gd':
                self.optimizer = tf.train.GradientDescentOptimizer(learning_rate=self.learning_rate).minimize(
                    self.loss)

            elif self.optimizer_type == 'momentum':
                self.optimizer = tf.train.MomentumOptimizer(learning_rate=self.learning_rate, momentum=0.95).minimize(self.loss)

            elif self.optimizer_type == 'rmsprop':
                self.optimizer = tf.train.RMSPropOptimizer(learning_rate=self.learning_rate).minimize(self.loss)

            init = tf.global_variables_initializer()
            self.sess = tf.Session()
            self.sess.run(init)

            # train
            for epoch in range(self.epochs):
                for i in range(0, len(train), self.batch_size):
                    cate_index_batch = category_index[i: i + self.batch_size]
                    wide_data_batch_x = wide_data[i: i + self.batch_size]
                    train_batch_x = train[i: i + self.batch_size]
                    batch_y = label[i: i + self.batch_size]

                    feed_dict = {
                        self.cate_index: cate_index_batch,
                        self.cont_feats: train_batch_x[self.continuous_feature].values.tolist(),
                        self.wide_input: wide_data_batch_x.values.tolist(),
                        self.deep_input: train_batch_x.values.tolist(),
                        self.label: batch_y
                    }
                    cost, opt = self.sess.run([self.loss, self.optimizer], feed_dict=feed_dict)
                metric = self.evaluate(wide_data, train, category_index, label)
                print('[%s] cost=%s, train-%s=%.4f' % (epoch + 1, cost, self.metric_type, metric))

    def predict(self, wide_input, deep_input, category_index):
        feed_dict = {
            self.cate_index: category_index,
            self.cont_feats: deep_input[self.continuous_feature].values.tolist(),
            self.wide_input: wide_input,
            self.deep_input: deep_input
        }
        y_pred = self.sess.run(self.out, feed_dict=feed_dict)
        return y_pred

    def evaluate(self, wide_input, deep_input, category_index, label):
        y_pred = self.predict(wide_input, deep_input, category_index)
        if self.metric_type == 'auc':
            return roc_auc_score(label, y_pred)
        elif self.metric_type == 'accuracy':
            return accuracy_score(label, y_pred)
        elif self.metric_type == 'logloss':
            return log_loss(label, y_pred)
        elif self.metric_type == 'rmse':
            return mean_squared_error(label, y_pred)

if __name__ == '__main__':
    print('read dataset...')
    train = pd.read_csv('data/train.csv')
    test = pd.read_csv('data/test.csv')
    y_train = pd.read_csv('data/y_train.csv').values.reshape(-1, 1)
    y_val = pd.read_csv('data/y_val.csv').values.reshape(-1, 1)

    continuous_feature = ['age', 'fnlwgt', 'education_num', 'capital_gain', 'capital_loss', 'hours_per_week']
    category_feature = ['workclass', 'education', 'marital_status', 'occupation', 'relationship', 'race', 'sex',
                        'native_country']
    cross_feature = [['education', 'occupation'], ['native_country', 'occupation']]
    dataParse = DataParse(continuous_feature=continuous_feature, category_feature=category_feature)
    dataParse.FeatureDictionary(train, test)
    cat_index = dataParse.parse(train)
    test_cat_index = dataParse.parse(test)

    model = Wide_Deep(continuous_feature=continuous_feature,
                      category_feature=category_feature,
                      cross_feature=cross_feature,
                      category_field_size=dataParse.category_field_size,
                      category_size=dataParse.category_size)
    model.fit(category_index=cat_index, train=train, label=y_train)
    if len(cross_feature) > 0:
        cross = model.get_cross_feature(test)
        wide_input = pd.concat([test, cross], axis=1)
    else:
        wide_input = test

    test_metric = model.evaluate(wide_input=wide_input, deep_input=test, category_index=test_cat_index, label=y_val)
    print('test-auc=%.4f' % test_metric)

