# Copyright (C) 2008-2012 Robert C. Kirby (Texas Tech University)
# Modified by Andrew T. T. McRae (Imperial College London)
#
# This file is part of FIAT (https://www.fenicsproject.org)
#
# SPDX-License-Identifier:    LGPL-3.0-or-later

from FIAT import (expansions, polynomial_set, dual_set,
                  finite_element, functional)
import numpy
from itertools import chain
from FIAT.check_format_variant import check_format_variant
from FIAT.quadrature_schemes import create_quadrature


def RTSpace(ref_el, degree):
    """Constructs a basis for the the Raviart-Thomas space
    (P_{degree-1})^d + P_{degree-1} x"""
    sd = ref_el.get_spatial_dimension()

    k = degree - 1
    vec_Pkp1 = polynomial_set.ONPolynomialSet(ref_el, k + 1, (sd,))

    dimPkp1 = expansions.polynomial_dimension(ref_el, k + 1)
    dimPk = expansions.polynomial_dimension(ref_el, k)
    dimPkm1 = expansions.polynomial_dimension(ref_el, k - 1)

    vec_Pk_indices = list(chain(*(range(i * dimPkp1, i * dimPkp1 + dimPk)
                                  for i in range(sd))))
    vec_Pk_from_Pkp1 = vec_Pkp1.take(vec_Pk_indices)

    Pkp1 = polynomial_set.ONPolynomialSet(ref_el, k + 1)
    PkH = Pkp1.take(list(range(dimPkm1, dimPk)))

    Q = create_quadrature(ref_el, 2 * (k + 1))

    # have to work on this through "tabulate" interface
    # first, tabulate PkH at quadrature points
    Qpts = Q.get_points()
    Qwts = Q.get_weights()

    PkH_at_Qpts = PkH.tabulate(Qpts)[(0,) * sd]
    Pkp1_at_Qpts = Pkp1.tabulate(Qpts)[(0,) * sd]

    x = Qpts.T
    xPkH_at_Qpts = numpy.zeros((PkH_at_Qpts.shape[0],
                                sd,
                                PkH_at_Qpts.shape[1]), "d")
    for i in range(PkH_at_Qpts.shape[0]):
        xPkH_at_Qpts[i] = PkH_at_Qpts[i] * x
    PkHx_coeffs = numpy.dot(xPkH_at_Qpts, Qwts[:, None] * Pkp1_at_Qpts.T)

    PkHx = polynomial_set.PolynomialSet(ref_el,
                                        k,
                                        k + 1,
                                        vec_Pkp1.get_expansion_set(),
                                        PkHx_coeffs)

    return polynomial_set.polynomial_set_union_normalized(vec_Pk_from_Pkp1, PkHx)


class RTDualSet(dual_set.DualSet):
    """Dual basis for Raviart-Thomas elements consisting of point
    evaluation of normals on facets of codimension 1 and internal
    moments against polynomials"""

    def __init__(self, ref_el, degree, variant, interpolant_deg):
        entity_ids = {}
        nodes = []

        sd = ref_el.get_spatial_dimension()
        t = ref_el.get_topology()

        if variant == "integral":
            facet = ref_el.get_facet_element()
            # Facet nodes are \int_F v\cdot n p ds where p \in P_{q-1}
            # degree is q - 1
            Q = create_quadrature(facet, interpolant_deg + degree - 1)
            Pq = polynomial_set.ONPolynomialSet(facet, degree - 1)
            Pq_at_qpts = Pq.tabulate(Q.get_points())[(0,)*(sd - 1)]
            nodes.extend(functional.IntegralMomentOfScaledNormalEvaluation(ref_el, Q, phi, f)
                         for f in range(len(t[sd - 1]))
                         for phi in Pq_at_qpts)

            # internal nodes. These are \int_T v \cdot p dx where p \in P_{q-2}^d
            if degree > 1:
                Q = create_quadrature(ref_el, interpolant_deg + degree - 2)
                Pkm1 = polynomial_set.ONPolynomialSet(ref_el, degree - 2)
                Pkm1_at_qpts = Pkm1.tabulate(Q.get_points())[(0,) * sd]
                nodes.extend(functional.IntegralMoment(ref_el, Q, phi, (d,), (sd,))
                             for d in range(sd)
                             for phi in Pkm1_at_qpts)

        elif variant == "point":
            # codimension 1 facets
            for i in range(len(t[sd - 1])):
                pts_cur = ref_el.make_points(sd - 1, i, sd + degree - 1)
                nodes.extend(functional.PointScaledNormalEvaluation(ref_el, i, pt)
                             for pt in pts_cur)

            # internal nodes.  Let's just use points at a lattice
            if degree > 1:
                pts = ref_el.make_points(sd, 0, sd + degree - 1)
                nodes.extend(functional.ComponentPointEvaluation(ref_el, d, (sd,), pt)
                             for d in range(sd)
                             for pt in pts)

        # sets vertices (and in 3d, edges) to have no nodes
        for i in range(sd - 1):
            entity_ids[i] = {}
            for j in range(len(t[i])):
                entity_ids[i][j] = []

        cur = 0

        # set codimension 1 (edges 2d, faces 3d) dof
        pts_facet_0 = ref_el.make_points(sd - 1, 0, sd + degree - 1)
        pts_per_facet = len(pts_facet_0)
        entity_ids[sd - 1] = {}
        for i in range(len(t[sd - 1])):
            entity_ids[sd - 1][i] = list(range(cur, cur + pts_per_facet))
            cur += pts_per_facet

        # internal nodes, if applicable
        entity_ids[sd] = {0: []}
        if degree > 1:
            num_internal_nodes = expansions.polynomial_dimension(ref_el,
                                                                 degree - 2)
            entity_ids[sd][0] = list(range(cur, cur + num_internal_nodes * sd))

        super(RTDualSet, self).__init__(nodes, ref_el, entity_ids)


class RaviartThomas(finite_element.CiarletElement):
    """
    The Raviart Thomas element

    :arg ref_el: The reference element.
    :arg degree: The degree.
    :arg variant: optional variant specifying the types of nodes.

    variant can be chosen from ["point", "integral", "integral(q)"]
    "point" -> dofs are evaluated by point evaluation. Note that this variant
    has suboptimal convergence order in the H(div)-norm
    "integral" -> dofs are evaluated by quadrature rules with the minimum
    degree required for unisolvence.
    "integral(q)" -> dofs are evaluated by quadrature rules with the minimum
    degree required for unisolvence plus q. You might want to choose a high
    quadrature degree to make sure that expressions will be interpolated
    exactly. This is important when you want to have (nearly) div-preserving
    interpolation.
    """

    def __init__(self, ref_el, degree, variant=None):

        variant, interpolant_deg = check_format_variant(variant, degree)

        poly_set = RTSpace(ref_el, degree)
        dual = RTDualSet(ref_el, degree, variant, interpolant_deg)
        formdegree = ref_el.get_spatial_dimension() - 1  # (n-1)-form
        super(RaviartThomas, self).__init__(poly_set, dual, degree, formdegree,
                                            mapping="contravariant piola")
