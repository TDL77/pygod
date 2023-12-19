# -*- coding: utf-8 -*-
"""Deep Outlier Aware Attributed Network Embedding (DONE)"""
# Author: Kay Liu <zliu234@uic.edu>
# License: BSD 2 clause

import torch
import warnings

from . import DeepDetector
from ..nn import DONEBase


class DONE(DeepDetector):
    """
    Deep Outlier Aware Attributed Network Embedding

    DONE consists of an attribute autoencoder and a structure
    autoencoder. It estimates five losses to optimize the model,
    including an attribute proximity loss, an attribute homophily loss,
    a structure proximity loss, a structure homophily loss, and a
    combination loss. It calculates three outlier scores, and averages
    them as an overall scores.

    .. note::
        This detector is transductive only. Using ``predict`` with
        unseen data will train the detector from scratch.

    See :cite:`bandyopadhyay2020outlier` for details.

    Parameters
    ----------
    hid_dim :  int, optional
        Hidden dimension of model. Default: ``64``.
    num_layers : int, optional
        Total number of layers in model. A half (floor) of the layers
        are for the encoder, the other half (ceil) of the layers are for
        decoders. Default: ``4``.
    dropout : float, optional
        Dropout rate. Default: ``0.``.
    weight_decay : float, optional
        Weight decay (L2 penalty). Default: ``0.``.
    act : callable activation function or None, optional
        Activation function if not None.
        Default: ``torch.nn.functional.relu``.
    backbone : torch.nn.Module
        The backbone of DONE is fixed to be MLP. Changing of this
        parameter will not affect the model. Default: ``None``.
    w1 : float, optional
        Weight of structure proximity loss. Default: ``0.2``.
    w2 : float, optional
        Weight of structure homophily loss. Default: ``0.2``.
    w3 : float, optional
        Weight of attribute proximity loss. Default: ``0.2``.
    w4 : float, optional
        Weight of attribute homophily loss. Default: ``0.2``.
    w5 : float, optional
        Weight of combination loss. Default: ``0.2``.
    contamination : float, optional
        The amount of contamination of the dataset in (0., 0.5], i.e.,
        the proportion of outliers in the dataset. Used when fitting to
        define the threshold on the decision function. Default: ``0.1``.
    lr : float, optional
        Learning rate. Default: ``0.004``.
    epoch : int, optional
        Maximum number of training epoch. Default: ``100``.
    gpu : int
        GPU Index, -1 for using CPU. Default: ``-1``.
    batch_size : int, optional
        Minibatch size, 0 for full batch training. Default: ``0``.
    num_neigh : int, optional
        Number of neighbors in sampling, -1 for all neighbors.
        Default: ``-1``.
    verbose : int, optional
        Verbosity mode. Range in [0, 3]. Larger value for printing out
        more log information. Default: ``0``.
    save_emb : bool, optional
        Whether to save the embedding. Default: ``False``.
    compile_model : bool, optional
        Whether to compile the model with ``torch_geometric.compile``.
        Default: ``False``.
    **kwargs
        Other parameters for the backbone model.

    Attributes
    ----------
    decision_score_ : torch.Tensor
        The outlier scores of the training data. Outliers tend to have
        higher scores. This value is available once the detector is
        fitted.
    threshold_ : float
        The threshold is based on ``contamination``. It is the
        :math:`N`*``contamination`` most abnormal samples in
        ``decision_score_``. The threshold is calculated for generating
        binary outlier labels.
    label_ : torch.Tensor
        The binary labels of the training data. 0 stands for inliers
        and 1 for outliers. It is generated by applying
        ``threshold_`` on ``decision_score_``.
    emb : torch.Tensor or tuple of torch.Tensor or None
        The learned node hidden embeddings of shape
        :math:`N \\times` ``hid_dim``. Only available when ``save_emb``
        is ``True``. When the detector has not been fitted, ``emb`` is
        ``None``. When the detector has multiple embeddings,
        ``emb`` is a tuple of torch.Tensor.
    attribute_score_ : torch.Tensor
        Attribute outlier score.
    structural_score_ : torch.Tensor
        Structural outlier score.
    combined_score_ : torch.Tensor
        Combined outlier score.
    """

    def __init__(self,
                 hid_dim=64,
                 num_layers=4,
                 dropout=0.,
                 weight_decay=0.,
                 act=torch.nn.functional.relu,
                 backbone=None,
                 w1=0.2,
                 w2=0.2,
                 w3=0.2,
                 w4=0.2,
                 w5=0.2,
                 contamination=0.1,
                 lr=4e-3,
                 epoch=100,
                 gpu=-1,
                 batch_size=0,
                 num_neigh=-1,
                 verbose=0,
                 save_emb=False,
                 compile_model=False,
                 **kwargs):

        if backbone is not None:
            warnings.warn("Backbone is not used in AdONE.")

        super(DONE, self).__init__(hid_dim=hid_dim,
                                   num_layers=1,
                                   dropout=dropout,
                                   weight_decay=weight_decay,
                                   act=act,
                                   contamination=contamination,
                                   lr=lr,
                                   epoch=epoch,
                                   gpu=gpu,
                                   batch_size=batch_size,
                                   num_neigh=num_neigh,
                                   verbose=verbose,
                                   save_emb=save_emb,
                                   compile_model=compile_model,
                                   **kwargs)

        self.w1 = w1
        self.w2 = w2
        self.w3 = w3
        self.w4 = w4
        self.w5 = w5
        self.num_layers = num_layers

        self.attribute_score_ = None
        self.structural_score_ = None
        self.combined_score_ = None

    def process_graph(self, data):
        DONEBase.process_graph(data)

    def init_model(self, **kwargs):
        self.attribute_score_ = torch.zeros(self.num_nodes)
        self.structural_score_ = torch.zeros(self.num_nodes)
        self.combined_score_ = torch.zeros(self.num_nodes)

        if self.save_emb:
            self.emb = (torch.zeros(self.num_nodes, self.hid_dim),
                        torch.zeros(self.num_nodes, self.hid_dim))

        return DONEBase(x_dim=self.in_dim,
                        s_dim=self.num_nodes,
                        hid_dim=self.hid_dim,
                        num_layers=self.num_layers,
                        dropout=self.dropout,
                        act=self.act,
                        w1=self.w1,
                        w2=self.w2,
                        w3=self.w3,
                        w4=self.w4,
                        w5=self.w5,
                        **kwargs).to(self.device)

    def forward_model(self, data, is_train=True):
        batch_size = data.batch_size
        node_idx = data.n_id

        x = data.x.to(self.device)
        s = data.s.to(self.device)
        edge_index = data.edge_index.to(self.device)

        x_, s_, h_a, h_s, dna, dns = self.model(x, s, edge_index)
        if 'active_mask' in data.keys():
            loss, oa, os, oc = self.model.loss_func(x[:batch_size][data.active_mask,:],
                                                    x_[:batch_size][data.active_mask,:],
                                                    s[:batch_size][data.active_mask,:],
                                                    s_[:batch_size][data.active_mask,:],
                                                    h_a[:batch_size][data.active_mask,:],
                                                    h_s[:batch_size][data.active_mask,:],
                                                    dna[:batch_size][data.active_mask,:],
                                                    dns[:batch_size][data.active_mask,:])
        else:
            loss, oa, os, oc = self.model.loss_func(x[:batch_size],
                                                    x_[:batch_size],
                                                    s[:batch_size],
                                                    s_[:batch_size],
                                                    h_a[:batch_size],
                                                    h_s[:batch_size],
                                                    dna[:batch_size],
                                                    dns[:batch_size])

        self.attribute_score_[node_idx[:batch_size]] = oa.detach().cpu()
        self.structural_score_[node_idx[:batch_size]] = os.detach().cpu()
        self.combined_score_[node_idx[:batch_size]] = oc.detach().cpu()

        return loss, ((oa + os + oc) / 3).detach().cpu()

    def decision_function(self, data, label=None):
        if data is not None:
            warnings.warn("This detector is transductive only. "
                          "Training from scratch with the input data.")
            self.fit(data, label)
        return self.decision_score_
