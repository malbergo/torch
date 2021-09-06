import torch
import numpy as np
from torch import nn
from ..factorized_tensors import TensorizedTensor
from .utils import suggest_shape
# Author: Cole Hawkins, with reshaping code taken from https://github.com/KhrulkovV/tt-pytorch
# License: BSD 3 clause


class FactorizedEmbedding(nn.Module):
    """
    Tensorized Embedding Layers For Efficient Model Compression

    Tensorized drop-in replacement for torch.nn.Embedding

    Parameters
    ----------
    num_embeddings : int, number of entries in the lookup table
    embedding_dim : int, number of dimensions per entry
    auto_reshape : bool, whether to use automatic reshaping for the embedding dimensions
    d : int or int tuple, number of reshape dimensions for both embedding table dimension
    tensorized_num_embeddings : int tuple, tensorized shape of the first embedding table dimension
    tensorized_embedding_dim : int tuple, tensorized shape of the second embedding table dimension
    factorization : str, tensor type
    rank : int tuple or str, tensor rank
    """
    def __init__(self,
                 num_embeddings,
                 embedding_dim,
                 auto_reshape=True,
                 d=(3, 3),
                 tensorized_num_embeddings=None,
                 tensorized_embedding_dim=None,
                 factorization='blocktt',
                 rank=8,
                 device=None,
                 dtype=None):
        super().__init__()

        if auto_reshape:
            try:
                assert tensorized_num_embeddings is None and tensorized_embedding_dim is None
            except:
                raise ValueError(
                    "Automated factorization enabled but tensor dimensions provided"
                )

            #if user provides an int, expand to tuple and assume 
            #each embedding dimension gets reshaped to the same number of dimensions
            if type(d) == int:
                d = (d, d)

            tensorized_num_embeddings = suggest_shape(num_embeddings, d[0])
            tensorized_embedding_dim = suggest_shape(embedding_dim, d[1])
            num_embeddings = np.prod(tensorized_num_embeddings)
            embedding_dim = np.prod(tensorized_embedding_dim)
        else:
            try:
                assert np.prod(
                    tensorized_num_embeddings) == num_embeddings and np.prod(
                        tensorized_embedding_dim) == embedding_dim
            except:
                raise ValueError(
                    "Must provide appropriate reshaping dimensions")

        self.num_embeddings = num_embeddings
        self.embedding_dim = embedding_dim
        self.tensor_shape = (tensorized_num_embeddings,
                             tensorized_embedding_dim)
        self.weight_shape = (self.num_embeddings, self.embedding_dim)

        self.factorization = factorization

        self.weight = TensorizedTensor.new(self.tensor_shape,
                                           rank=rank,
                                           factorization=self.factorization,
                                           device=device,
                                           dtype=dtype)
        self.reset_parameters()

        self.rank = self.weight.rank

    def reset_parameters(self):
        #Parameter initialization from Yin et al.
        #TT-Rec: Tensor Train Compression for Deep Learning Recommendation Model Embeddings
        target_stddev = 1 / np.sqrt(3 * self.num_embeddings)
        with torch.no_grad():
            self.weight.normal_(0, target_stddev)

    def forward(self, input):

        #to handle case where input is not 1-D
        output_shape = (*input.shape, self.embedding_dim)

        input = input.view(-1)

        embeddings = self.weight[input, :]

        #CPTensorized returns CPTensorized when indexing
        if self.factorization == 'CP':
            embeddings = embeddings.to_matrix()

        #TuckerTensorized returns tensor not matrix,
        #and requires reshape not view for contiguous
        elif self.factorization == 'Tucker':
            embeddings = embeddings.reshape(input.shape[0], -1)

        return embeddings.view(output_shape)

    @classmethod
    def from_embedding(cls,
                       embedding_layer,
                       rank=8,
                       factorization='blocktt',
                       decompose_weights=True,
                       auto_reshape=True,
                       decomposition_kwargs=dict(),
                       **kwargs):
        """
        Create a tensorized embedding layer from a regular embedding layer

        Parameters
        ----------
        embedding_layer : torch.nn.Embedding
        rank : int tuple or str, tensor rank
        factorization : str, tensor type
        decompose_weights: bool, decompose weights and use for initialization
        auto_reshape: bool, automatically reshape dimensions for TensorizedTensor
        decomposition_kwargs: dict, specify kwargs for the decomposition
        """
        embeddings, embedding_dim = embedding_layer.weight.shape

        instance = cls(embeddings,
                       embedding_dim,
                       auto_reshape=auto_reshape,
                       factorization=factorization,
                       rank=rank,
                       **kwargs)

        if decompose_weights:
            with torch.no_grad():
                instance.weight.init_from_matrix(embedding_layer.weight.data,
                                                 **decomposition_kwargs)

        else:
            instance.reset_parameters()

        return instance
