#!/usr/bin/env python
# encoding: utf-8

# The MIT License (MIT)

# Copyright (c) 2018-2020 CNRS

# Permission is hereby granted, free of charge, to any person obtaining a copy
# of this software and associated documentation files (the "Software"), to deal
# in the Software without restriction, including without limitation the rights
# to use, copy, modify, merge, publish, distribute, sublicense, and/or sell
# copies of the Software, and to permit persons to whom the Software is
# furnished to do so, subject to the following conditions:

# The above copyright notice and this permission notice shall be included in
# all copies or substantial portions of the Software.

# THE SOFTWARE IS PROVIDED "AS IS", WITHOUT WARRANTY OF ANY KIND, EXPRESS OR
# IMPLIED, INCLUDING BUT NOT LIMITED TO THE WARRANTIES OF MERCHANTABILITY,
# FITNESS FOR A PARTICULAR PURPOSE AND NONINFRINGEMENT. IN NO EVENT SHALL THE
# AUTHORS OR COPYRIGHT HOLDERS BE LIABLE FOR ANY CLAIM, DAMAGES OR OTHER
# LIABILITY, WHETHER IN AN ACTION OF CONTRACT, TORT OR OTHERWISE, ARISING FROM,
# OUT OF OR IN CONNECTION WITH THE SOFTWARE OR THE USE OR OTHER DEALINGS IN THE
# SOFTWARE.

# AUTHORS
# Hervé BREDIN - http://herve.niderb.fr

"""Speech activity detection"""

from typing import Optional
from typing import Text

import numpy as np
import torch
import torch.nn as nn
from .base import LabelingTask
from .base import LabelingTaskGenerator
from pyannote.audio.train.task import Task, TaskType, TaskOutput
from ..gradient_reversal import GradientReversal
from pyannote.audio.models.models import RNN
from pyannote.audio.features.wrapper import Wrappable
from pyannote.database import Protocol
from pyannote.database import Subset
from pyannote.audio.train.model import Resolution
from pyannote.audio.train.model import Alignment


class SpeechActivityDetectionGenerator(LabelingTaskGenerator):
    """Batch generator for training speech activity detection

    Parameters
    ----------
    task : Task
        Task
    feature_extraction : Wrappable
        Describes how features should be obtained.
        See pyannote.audio.features.wrapper.Wrapper documentation for details.
    protocol : Protocol
    subset : {'train', 'development', 'test'}, optional
        Protocol and subset.
    resolution : `pyannote.core.SlidingWindow`, optional
        Override `feature_extraction.sliding_window`. This is useful for
        models that include the feature extraction step (e.g. SincNet) and
        therefore output a lower sample rate than that of the input.
        Defaults to `feature_extraction.sliding_window`
    alignment : {'center', 'loose', 'strict'}, optional
        Which mode to use when cropping labels. This is useful for models that
        include the feature extraction step (e.g. SincNet) and therefore use a
        different cropping mode. Defaults to 'center'.
    duration : float, optional
        Duration of audio chunks. Defaults to 2s.
    batch_size : int, optional
        Batch size. Defaults to 32.
    per_epoch : float, optional
        Force total audio duration per epoch, in days.
        Defaults to total duration of protocol subset.
    mask : str, optional
        When provided, protocol files are expected to contain a key named after
        this `mask` variable and providing a `SlidingWindowFeature` instance.
        Generated batches will contain an additional "mask" key (on top of
        existing "X" and "y" keys) computed as an excerpt of `current_file[mask]`
        time-aligned with "y". Defaults to not add any "mask" key.

    """

    def __init__(
        self,
        task: Task,
        feature_extraction: Wrappable,
        protocol: Protocol,
        subset: Subset = "train",
        resolution: Optional[Resolution] = None,
        alignment: Optional[Alignment] = None,
        duration: float = 2.0,
        batch_size: int = 32,
        per_epoch: float = None,
        mask: Text = None,
    ):

        super().__init__(
            task,
            feature_extraction,
            protocol,
            subset=subset,
            resolution=resolution,
            alignment=alignment,
            duration=duration,
            batch_size=batch_size,
            per_epoch=per_epoch,
            exhaustive=False,
            mask=mask,
            local_labels=True,
        )

    def postprocess_y(self, Y: np.ndarray) -> np.ndarray:
        """Generate labels for speech activity detection

        Parameters
        ----------
        Y : (n_samples, n_speakers) numpy.ndarray
            Discretized annotation returned by
            `pyannote.core.utils.numpy.one_hot_encoding`.

        Returns
        -------
        y : (n_samples, 1) numpy.ndarray

        See also
        --------
        `pyannote.core.utils.numpy.one_hot_encoding`
        """

        # number of speakers for each frame
        speaker_count = np.sum(Y, axis=1, keepdims=True)

        # mark speech regions as such
        return np.int64(speaker_count > 0)

    @property
    def specifications(self):
        specs = {
            "task": self.task,
            "X": {"dimension": self.feature_extraction.dimension},
            "y": {"classes": ["non_speech", "speech"]},
        }

        for key, classes in self.file_labels_.items():

            # TODO. add an option to handle this list
            # TODO. especially useful for domain-adversarial stuff
            if key in ["duration", "audio", "uri"]:
                continue
            specs[key] = {"classes": classes}

        return specs


class SpeechActivityDetection(LabelingTask):
    """Train speech activity (and overlap) detection

    Parameters
    ----------
    duration : float, optional
        Duration of sub-sequences. Defaults to 3.2s.
    batch_size : int, optional
        Batch size. Defaults to 32.
    per_epoch : float, optional
        Total audio duration per epoch, in days.
        Defaults to one day (1).
    """

    def get_batch_generator(
        self,
        feature_extraction,
        protocol,
        subset: Subset = "train",
        resolution=None,
        alignment=None,
    ):
        """
        resolution : `pyannote.core.SlidingWindow`, optional
            Override `feature_extraction.sliding_window`. This is useful for
            models that include the feature extraction step (e.g. SincNet) and
            therefore output a lower sample rate than that of the input.
        alignment : {'center', 'loose', 'strict'}, optional
            Which mode to use when cropping labels. This is useful for models
            that include the feature extraction step (e.g. SincNet) and
            therefore use a different cropping mode. Defaults to 'center'.
        """
        return SpeechActivityDetectionGenerator(
            self.task,
            feature_extraction,
            protocol,
            subset=subset,
            resolution=resolution,
            alignment=alignment,
            duration=self.duration,
            per_epoch=self.per_epoch,
            batch_size=self.batch_size,
        )


class DomainAwareSpeechActivityDetection(SpeechActivityDetection):
    """Domain-aware speech activity detection

    Trains speech activity detection and domain classification jointly.

    Parameters
    ----------
    domain : `str`, optional
        Batch key to use as domain. Defaults to 'domain'.
        Could be 'database' or 'uri' for instance.
    attachment : `int`, optional
        Intermediate level where to attach the domain classifier.
        Defaults to -1. Passed to `return_intermediate` in models supporting it.
    rnn: `dict`, optional
        Parameters of the RNN used in the domain classifier.
        See `pyannote.audio.models.models.RNN` for details.
    domain_loss : `str`, optional
        Loss function to use. Defaults to 'NLLLoss'.
    """

    DOMAIN_PT = "{train_dir}/weights/{epoch:04d}.domain.pt"

    def __init__(
        self, domain="domain", attachment=-1, rnn=None, domain_loss="NLLLoss", **kwargs
    ):
        super().__init__(**kwargs)
        self.domain = domain
        self.attachment = attachment

        if rnn is None:
            rnn = dict()
        self.rnn = rnn

        self.domain_loss = domain_loss
        if self.domain_loss == "NLLLoss":
            # Default value
            self.domain_loss_ = nn.NLLLoss()
            self.activation_ = nn.LogSoftmax(dim=1)

        elif self.domain_loss == "MSELoss":
            self.domain_loss_ = nn.MSELoss()
            self.activation_ = nn.Sigmoid()

        else:
            msg = f"{domain_loss} has not been implemented yet."
            raise NotImplementedError(msg)

    def more_parameters(self):
        """Initialize trainable trainer parameters

        Yields
        ------
        parameter : nn.Parameter
            Trainable trainer parameters
        """

        domain_classifier_rnn = RNN(
            n_features=self.model.intermediate_dimension(self.attachment), **self.rnn
        )

        n_classes = len(self.specifications[self.domain]["classes"])
        domain_classifier_linear = nn.Linear(
            domain_classifier_rnn.dimension, n_classes, bias=True
        ).to(self.device)

        self.domain_classifier_ = nn.Sequential(
            domain_classifier_rnn, domain_classifier_linear
        ).to(self.device)

        # TODO: check if we really need to do this .to(self.device) twice

        return self.domain_classifier_.parameters()

    def load_more(self, model_pt=None) -> bool:
        """Load classifier from disk"""

        if model_pt is None:
            domain_pt = self.DOMAIN_PT.format(
                train_dir=self.train_dir_, epoch=self.epoch_
            )
        else:
            domain_pt = model_pt.with_suffix(".domain.pt")

        domain_classifier_state = torch.load(
            domain_pt, map_location=lambda storage, loc: storage
        )
        self.domain_classifier_.load_state_dict(domain_classifier_state)

        # FIXME add support for different domains
        return True

    def save_more(self):
        """Save domain classifier to disk"""

        domain_pt = self.DOMAIN_PT.format(train_dir=self.train_dir_, epoch=self.epoch_)
        torch.save(self.domain_classifier_.state_dict(), domain_pt)

    def batch_loss(self, batch):
        """Compute loss for current `batch`

        Parameters
        ----------
        batch : `dict`
            ['X'] (`numpy.ndarray`)
            ['y'] (`numpy.ndarray`)

        Returns
        -------
        batch_loss : `dict`
            ['loss'] (`torch.Tensor`) : Loss
        """

        # forward pass
        X = torch.tensor(batch["X"], dtype=torch.float32, device=self.device_)
        fX, intermediate = self.model_(X, return_intermediate=self.attachment)

        # speech activity detection
        fX = fX.view((-1, self.n_classes_))
        target = (
            torch.tensor(batch["y"], dtype=torch.int64, device=self.device_)
            .contiguous()
            .view((-1,))
        )

        weight = self.weight
        if weight is not None:
            weight = weight.to(device=self.device_)
        loss = self.loss_func_(fX, target, weight=weight)

        # domain classification
        domain_target = torch.tensor(
            batch[self.domain], dtype=torch.int64, device=self.device_
        )

        domain_scores = self.activation_(self.domain_classifier_(intermediate))

        domain_loss = self.domain_loss_(domain_scores, domain_target)

        return {
            "loss": loss + domain_loss,
            "loss_domain": domain_loss,
            "loss_task": loss,
        }


class DomainAdversarialSpeechActivityDetection(DomainAwareSpeechActivityDetection):
    """Domain Adversarial speech activity detection

    Parameters
    ----------
    domain : `str`, optional
        Batch key to use as domain. Defaults to 'domain'.
        Could be 'database' or 'uri' for instance.
    attachment : `int`, optional
        Intermediate level where to attach the domain classifier.
        Defaults to -1. Passed to `return_intermediate` in models supporting it.
    alpha : `float`, optional
        Coefficient multiplied with the domain loss
    """

    def __init__(self, domain="domain", attachment=-1, alpha=1.0, **kwargs):
        super().__init__(domain=domain, attachment=attachment, **kwargs)
        self.alpha = alpha
        self.gradient_reversal_ = GradientReversal()

    def batch_loss(self, batch):
        """Compute loss for current `batch`

        Parameters
        ----------
        batch : `dict`
            ['X'] (`numpy.ndarray`)
            ['y'] (`numpy.ndarray`)

        Returns
        -------
        batch_loss : `dict`
            ['loss'] (`torch.Tensor`) : Loss
        """
        # forward pass
        X = torch.tensor(batch["X"], dtype=torch.float32, device=self.device_)

        fX, intermediate = self.model_(X, return_intermediate=self.attachment)

        # speech activity detection
        fX = fX.view((-1, self.n_classes_))

        target = (
            torch.tensor(batch["y"], dtype=torch.int64, device=self.device_)
            .contiguous()
            .view((-1,))
        )

        weight = self.weight
        if weight is not None:
            weight = weight.to(device=self.device_)

        loss = self.loss_func_(fX, target, weight=weight)

        # domain classification
        domain_target = torch.tensor(
            batch[self.domain], dtype=torch.int64, device=self.device_
        )

        domain_scores = self.activation_(
            self.domain_classifier_(self.gradient_reversal_(intermediate))
        )

        if self.domain_loss == "MSELoss":
            # One hot encode domain_target for Mean Squared Error Loss
            nb_domains = domain_scores.shape[1]
            identity_mat = torch.sparse.torch.eye(nb_domains, device=self.device_)
            domain_target = identity_mat.index_select(dim=0, index=domain_target)

        domain_loss = self.domain_loss_(domain_scores, domain_target)

        return {
            "loss": loss + self.alpha * domain_loss,
            "loss_domain": domain_loss,
            "loss_task": loss,
        }
