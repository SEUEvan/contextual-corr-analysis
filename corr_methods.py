import torch 
from tqdm import tqdm
from itertools import product as p
import json
import numpy as np
import h5py


class Method(object):
    """
    Abstract representation of a correlation method. 

    Example instances are MaxCorr, MinCorr, LinReg, SVCCA, CKA. 
    """
    def __init__(self, representation_files, layer=None, first_half_only=False,
                 second_half_only=False):
        self.representation_files = [line.strip() for line in representation_files]
        self.first_half_only = first_half_only
        self.second_half_only = second_half_only

    def load_representations(self, limit=None):
        """
        Load data. 

        Set `self.num_neurons_d` and `self.representations_d`. 
        """

        self.num_neurons_d = {}
        self.representations_d = {}

        for fname in tqdm(representation_files, desc='loading'):
            # this (the formatting) follows contexteval:
            # https://github.com/nelson-liu/contextual-repr-analysis/blob/master/contexteval/contextualizers/precomputed_contextualizer.py
            # Create `activations_h5`, `sentence_d`, `indices`
            activations_h5 = h5py.File(fname)
            sentence_d = json.loads(activations_h5['sentence_to_index'][0])
            temp = {}
            for k, v in sentence_d.items():
                temp[v] = k
            sentence_d = temp # {str ix, sentence}
            indices = list(sentence_d.keys())[:limit]

            # Create `representations_l`
            representations_l = []
            for sentence_ix in indices: 
                # Create `activations`
                activations = torch.FloatTensor(activations_h5[sentence_ix])
                if not (activations.dim() == 2 or activations.dim() == 3):
                    raise ValueError('Improper array dimension in file: ' + fname +
                                     "\nShape: " + str(activations.shape))

                # Create `representations`
                representations = activations
                if activations.dim() == 3:
                    if self.layer is not None: 
                        representations = activations[self.layer] 
                    else:
                        # use the top layer by default
                        representations = activations[-1]
                if self.first_half_only: 
                    representations = torch.chunk(representations, chunks=2, dim=-1)[0]
                elif self.second_half_only:
                    representations = torch.chunk(representations, chunks=2, dim=-1)[1]

                representations_l.append(representations)

            self.num_neurons_d[fname] = representations_l[0].size()[1]
            self.representations_d[fname] = torch.cat(representations_l) # TO DO: .cpu()?

    def compute_correlations(self):
        raise NotImplementedError

    def write_correlations(self):
        raise NotImplementedError


class MaxMinCorr(Method):
    def __init__(self, representation_files):
        super().__init__(representation_files)

    def compute_correlations(self, op):
        """
        Set `self.correlations`, `self.clusters`, `self.neuron_sort`. 
        """

        # Set `means_d`, `stdevs_d`
        means_d = {}
        stdevs_d = {}
        for network in tqdm(self.representations_d, desc='mu, sigma'):
            t = self.representations_d[network]

            means_d[network] = t.mean(0, keepdim=True)
            stdevs_d[network] = (t - means_d[network]).pow(2).mean(0, keepdim=True).pow(0.5)

        # Set `self.correlations`
        # {network: {other: tensor}}
        self.correlations = {network: {} for network in self.representations_d}
        num_words = list(self.representations_d.values())[0].size()[0] # TO DO: make more elegant

        for network, other_network in tqdm(p(self.representations_d,
                                             self.representations_d),
                                           desc='correlate',
                                           total=len(self.representations_d)**2):
            if network == other_network:
                continue

            if other_network in self.correlations[network].keys(): # TO DO: optimize?
                continue

            t1 = self.representations_d[network] # "tensor"
            t2 = self.representations_d[other_network] 
            m1 = means_d[network] # "means"
            m2 = means_d[other_network]
            s1 = stdevs_d[network] # "stdevs"
            s2 = stdevs_d[other_network]

            covariance = (torch.mm(t1.t(), t2) / num_words # E[ab]
                          - torch.mm(m1.t(), m2)) # E[a]E[b]
            correlation = covariance / torch.mm(s1.t(), s2)

            correlation = correlation.cpu().numpy()
            self.correlations[network][other_network] = correlation
            self.correlations[other_network][network] = correlation.T

        # Set `self.clusters`
        # {network: {neuron: {other: other_neuron}}}
        self.clusters = {network: {} for network in self.representations_d} 
        for network in tqdm(self.representations_d, desc='self.clusters',
                            total=len(self.representations_d)):
            for neuron in range(self.num_neurons_d[network]): 
                self.clusters[network][neuron] = {
                    other : max(range(self.num_neurons_d[other]),
                                key = lambda i: abs(self.correlations[network][other][neuron][i])) 
                     for other in self.correlations[network]
                }

        # Set `self.neuron_sort`
        # {network, sorted_list}
        self.neuron_sort = {} 
        # Sort neurons by worst (or best) best correlation with another neuron
        # in another network.
        for network in tqdm(self.representations_d, desc='annotation'):
            self.neuron_sort[network] = sorted(
                range(self.num_neurons_d[network]),
                key = lambda i : op(
                    abs(self.correlations[network][other][i][self.clusters[network][i][other]])
                    for other in self.clusters[network][i]),
                reverse=True
            )


    def write_correlations(self, output_file):

        # For each network, created an "annotated sort"
        self.neuron_notated_sort = {}
        for network in tqdm(self.representations_d, desc='write'):
            self.neuron_notated_sort[network] = [
                    (
                        neuron, 
                        {
                            '%s:%d' % (other, self.clusters[network][neuron][other],):
                            float(self.correlations[network][other][neuron][self.clusters[network][neuron][other]])
                            for other in self.clusters[network][neuron]
                        }
                    )
                    for neuron in self.neuron_sort[network]
                ]
        json.dump(neuron_notated_sort, open(output_file, 'w'), indent = 4)


class MaxCorr(MaxMinCorr):
    # TO DO: test (I don't think it's wrong, though)
    def __init__(self, representation_files):
        super().__init__(representation_files)

    def compute_correlations(self):
        super().compute_correlations(max)


class MinCorr(MaxMinCorr):
    # TO DO: test (I don't think it's wrong, though)
    def __init__(self, representation_files):
        super().__init__(representation_files)

    def compute_correlations(self):
        super().compute_correlations(min)


class LinReg(Method):
    def __init__(self, representation_files):
        super().__init__(representation_files)

    def compute_correlations(self):
        # Set `means_d`, `stdevs_d`, normalize to mean 0 std 1
        means_d = {}
        stdevs_d = {}

        for network in tqdm(self.representations_d, desc='mu, sigma'):
            t = self.representations_d[network]
            means = t.mean(0, keepdim=True)
            stdevs = (t - means).pow(2).mean(0, keepdim=True).pow(0.5)

            means_d[network] = means
            stdevs_d[network] = stdevs
            self.representations_d[network] = (t - means) / stdevs

        # Set `self.errors`
        # {network: {other: error_tensor}}
        for network, other_network in tqdm(p(self.representations_d,
                                             self.representations_d), desc='correlate',
                                           total=len(self.representations_d)**2):
            if network == other_network:
                continue

            # Try to predict this network given the other one
            X = self.representations_d[other_network].cpu().numpy()
            Y = self.representations_d[network].cpu().numpy()

            # solve with ordinary least squares 
            error = np.linalg.lstsq(X, Y, rcond=None)[1] # TO DO: don't use numpy, or at least use CUDA
            # Possibilities are use torch (torch.svd or smth), or use another library (cupy)
            if len(error) == 0:
                raise ValueError('np.linalg.lstsq returned errors of len 0 for
                input\nX: ' + str(X) + '\nY: ' + str(Y)) 
            error = torch.from_numpy(error)

            self.errors[network][other_network] = error

        # Set `self.neuron_sort`
        # {network: sorted_list}
        self.neuron_sort = {}
        # Sort neurons by worst correlation (highest regression error) with another network
        for network in tqdm(self.representations_d, desc='annotation'):
            self.neuron_sort[network] = sorted(
                range(self.num_neurons_d[network]),
                key = lambda i: max(
                    self.errors[network][other][i] 
                    for other in self.errors[network]
                )
            )


    def write_correlations(self, output_file):

        self.neuron_notated_sort = {}
        # For each network, created an "annotated sort"
        for network in tqdm(self.representations_d, desc='write'):
            # Annotate each neuron with its associated cluster
            self.neuron_notated_sort[network] = [
                (
                    neuron,
                    {
                        other: self.errors[network][other][neuron]
                        for other in self.errors[network]
                    }
                )
                for neuron in self.neuron_sort[network]
            ]

        json.dump(self.neuron_notated_sort, open(output_file, 'w'), indent = 4)


class SVCCA(Method):
    def __init__(self, representation_files, percent_variance=0.99, normalize_dimensions=False):
        super().__init__(representation_files)

        self.percent_variance = percent_variance
        self.normalize_dimensions = normalize_dimensions

    def compute_correlations(self):
        # Whiten dimensions
        if self.normalize_dimensions:
            for network in tqdm(self.representations_d, desc='mu, sigma'):
                self.representations_d[network] -= self.representations_d[network].mean(0)
                self.representations_d[network] /= self.representations_d[network].std(0)

        # PCA to get independent components
        whitening_transforms = {}
        for network in tqdm(self.representations_d, desc='pca'):
            X = self.representations_d[network]
            covariance = torch.mm(X.t(), X) / (X.size()[0] - 1)

            e, v = torch.eig(covariance, eigenvectors = True)

            # Sort by eigenvector magnitude
            magnitudes, indices = torch.sort(torch.abs(e[:, 0]), dim = 0, descending = True)
            se, sv = e[:, 0][indices], v.t()[indices].t()

            # Figure out how many dimensions account for 99% of the variance
            var_sums = torch.cumsum(se, 0)
            wanted_size = torch.sum(var_sums.lt(var_sums[-1] * args.percent_variance))

            print('For network', network, 'wanted size is', wanted_size)

            # This matrix has size (dim) x (dim)
            whitening_transform = torch.mm(sv, torch.diag(se ** -0.5))

            # We wish to cut it down to (dim) x (wanted_size)
            whitening_transforms[network] = whitening_transform[:, :wanted_size]

            #print(covariance[:10, :10])
            #print(torch.mm(whitening_transforms[network], whitening_transforms[network].t())[:10, :10])

        # CCA to get shared space
        self.transforms = {}
        for a, b in tqdm(p(self.representations_d, self.representations_d), desc = 'cca', total = len(self.representations_d) ** 2):
            if a is b or (a, b) in self.transforms or (b, a) in self.transforms:
                continue

            X, Y = self.representations_d[a], self.representations_d[b]

            # Apply PCA transforms to get independent things
            X = torch.mm(X, whitening_transforms[a])
            Y = torch.mm(Y, whitening_transforms[b])

            # Get a correlation matrix
            correlation_matrix = torch.mm(X.t(), Y) / (X.size()[0] - 1)

            # Perform SVD for CCA.
            # u s vt = Xt Y
            # s = ut Xt Y v
            u, s, v = torch.svd(correlation_matrix)

            X = torch.mm(X, u).cpu()
            Y = torch.mm(Y, v).cpu()

            self.transforms[a, b] = {
                a: whitening_transforms[a].mm(u),
                b: whitening_transforms[b].mm(v)
            }


    def write_correlations(self, output_file):

        torch.save(self.transforms, output_file)


# https://debug-ml-iclr2019.github.io/cameraready/DebugML-19_paper_9.pdf
class CKA(Method):

    def __init__(self, representation_files, normalize_dimensions=True):

        super().__init__(representation_files)
        self.normalize_dimensions = normalize_dimensions


    def compute_correlations(self):

        # Whiten dimensions
        if self.normalize_dimensions:
            for network in tqdm(self.representations_d, desc='mu, sigma'):
                self.representations_d[network] -= self.representations_d[network].mean(0)
                # TODO: might not need to normalize, only center
                self.representations_d[network] /= self.representations_d[network].std(0)

        # CKA to get shared space
        self.similarities = {}
        for a, b in tqdm(p(self.representations_d, self.representations_d), desc = 'cca', total = len(self.representations_d) ** 2):
            if a is b or (a, b) in self.transforms or (b, a) in self.transforms:
                continue

            X, Y = self.representations_d[a], self.representations_d[b]        

            self.similarities[a, b] = torch.norm(torch.mm(Y.t(), X), p='fro').pow(2) / ( 
                torch.norm(torch.mm(X.t(), X), p='fro') * torch.norm(torch.mm(Y.to(), Y), p='fro')
                )


    def write_correlations(self, output_file):

        torch.save(self.transforms, output_file)

