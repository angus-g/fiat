import pymbolic.primitives as p
import numpy as np
from ast import Recipe, IndexSum


class UndefinedError(Exception):
    def __init__(self, *args, **kwargs):
        Exception.__init__(self, *args, **kwargs)


class FiniteElementBase(object):

    def __init__(self):
        pass

    @property
    def cell(self):
        '''Return the reference cell on which we are defined.
        '''

        return self._cell

    @property
    def degree(self):
        '''Return the degree of the embedding polynomial space.

        In the tensor case this is a tuple.
        '''

        return self._degree

    @property
    def entity_dofs(self):
        '''Return the map of topological entities to degrees of
        freedom for the finite element.

        Note that entity numbering needs to take into account the tensor case.
        '''

        raise NotImplementedError

    @property
    def entity_closure_dofs(self):
        '''Return the map of topological entities to degrees of
        freedom on the closure of those entities for the finite element.'''

        raise NotImplementedError

    @property
    def facet_support_dofs(self):
        '''Return the map of facet id to the degrees of freedom for which the
        corresponding basis functions take non-zero values.'''

        raise NotImplementedError

    @property
    def dofs_shape(self):
        '''Return a tuple indicating the number of degrees of freedom in the
        element. For example a scalar quadratic Lagrange element on a triangle
        would return (6,) while a vector valued version of the same element
        would return (6, 2)'''

        raise NotImplementedError

    def field_evaluation(self, field_var, q, kernel_data, derivative=None,
                         pullback=None):
        '''Return code for evaluating a known field at known points on the
        reference element.

        :param field_var: the coefficient of the field at each basis function
        :param q: a :class:`.PointIndex` corresponding to the points
            at which to evaluate.
        :param kernel_data: the :class:`.KernelData` object corresponding
            to the current kernel.
        :param derivative: the derivative to take of the test function.
        :param pullback: whether to pull back to the reference cell.
        '''

        raise NotImplementedError

    def basis_evaluation(self, q, kernel_data, derivative=None,
                         pullback=None):
        '''Return code for evaluating a known field at known points on the
        reference element.

        :param field_var: the coefficient of the field at each basis function
        :param q: a :class:`.PointIndex` corresponding to the points
            at which to evaluate.
        :param kernel_data: the :class:`.KernelData` object corresponding
            to the current kernel.
        :param derivative: the derivative to take of the test function.
        :param pullback: whether to pull back to the reference cell.
        '''

        raise NotImplementedError

    def moment_evaluation(self, value, weights, q, kernel_data,
                          derivative=None, pullback=None):
        '''Return code for evaluating:

        .. math::

            \int \mathrm{value} : v\, \mathrm{d}x

        where :math:`v` is a test function or the derivative of a test
        function, and : is the inner product operator.

        :param value: an expression. The free indices in value must match those in v.
        :param weights: a point set of quadrature weights.
        :param q: a :class:`.PointIndex` corresponding to the points
            at which to evaluate.
        :param kernel_data: the :class:`.KernelData` object corresponding to the current kernel.
        :param derivative: the derivative to take of the test function.
        :param pullback: whether to pull back to the reference cell.
        '''

        raise NotImplementedError

    def dual_evaluation(self, kernel_data):
        '''Return code for evaluating an expression at the dual set.

        Note: what does the expression need to look like?
        '''

        raise NotImplementedError


class ScalarElementMixin(object):
    """Mixin class containing field evaluation and moment rules for scalar
    valued elements."""
    def field_evaluation(self, field_var, q,
                         kernel_data, derivative=None, pullback=True):

        kernel_data.kernel_args.add(field_var)

        basis = self.basis_evaluation(q, kernel_data, derivative, pullback)
        (d, b, p_) = basis.indices
        phi = basis.body

        expr = IndexSum(b, field_var[b[0]] * phi)

        return Recipe((d, (), p), expr)

    def moment_evaluation(self, value, weights, q,
                          kernel_data, derivative=None, pullback=True):

        basis = self.basis_evaluation(q, kernel_data, derivative, pullback)
        (d, b, p__) = basis.indices
        phi = basis.body

        (d_, b_, p_) = value.indices
        psi = value.replace_indices(zip(d_ + p_, d + p__)).body

        w = weights.kernel_variable("w", kernel_data)

        expr = psi * phi * w[p__]

        if pullback:
            expr *= kernel_data.detJ

        return Recipe(((), b + b_, ()), IndexSum(p__, expr))


class FiatElementBase(ScalarElementMixin, FiniteElementBase):
    """Base class for finite elements for which the tabulation is provided
    by FIAT."""
    def __init__(self, cell, degree):
        super(FiatElementBase, self).__init__()

        self._cell = cell
        self._degree = degree

    @property
    def entity_dofs(self):
        '''Return the map of topological entities to degrees of
        freedom for the finite element.

        Note that entity numbering needs to take into account the tensor case.
        '''

        return self._fiat_element.entity_dofs()

    @property
    def entity_closure_dofs(self):
        '''Return the map of topological entities to degrees of
        freedom on the closure of those entities for the finite element.'''

        return self._fiat_element.entity_closure_dofs()

    @property
    def facet_support_dofs(self):
        '''Return the map of facet id to the degrees of freedom for which the
        corresponding basis functions take non-zero values.'''

        return self._fiat_element.entity_support_dofs()

    def _tabulate(self, points, derivative):

        if derivative:
            tab = self._fiat_element.tabulate(1, points.points)

            ind = np.eye(points.points.shape[1], dtype=int)

            return np.array([tab[tuple(i)] for i in ind])
        else:
            return self._fiat_element.tabulate(0, points.points)[
                tuple([0] * points.points.shape[1])]

    def _tabulated_basis(self, points, kernel_data, derivative):

        static_key = (id(self), id(points), id(derivative))

        if static_key in kernel_data.static:
            phi = kernel_data.static[static_key][0]
        else:
            phi = p.Variable(("d" if derivative else "") +
                             kernel_data.tabulation_variable_name(self, points))
            data = self._tabulate(points, derivative)
            kernel_data.static[static_key] = (phi, lambda: data)

        return phi
