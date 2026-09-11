from __future__ import annotations

import math
from typing import Sequence

Matrix = list[list[float]]


def identity(size: int) -> Matrix:
    return [[1.0 if i == j else 0.0 for j in range(size)] for i in range(size)]


def _is_symmetric(matrix: Sequence[Sequence[float]], tolerance: float) -> bool:
    size = len(matrix)
    for i in range(size):
        for j in range(i + 1, size):
            if abs(matrix[i][j] - matrix[j][i]) > tolerance:
                return False
    return True


def symmetrize(matrix: Matrix) -> Matrix:

    size = len(matrix)
    return [[0.5 * (matrix[i][j] + matrix[j][i]) for j in range(size)] for i in range(size)]


def jacobi_eigen(
    matrix: Sequence[Sequence[float]],
    *,
    max_sweeps: int = 100,
    tolerance: float = 1e-14,
) -> tuple[tuple[float, ...], Matrix]:

    size = len(matrix)
    if size == 0:
        raise ValueError("the eigendecomposition of an empty matrix is undefined")
    for row in matrix:
        if len(row) != size:
            raise ValueError("the matrix is not square")
    if not _is_symmetric(matrix, tolerance=1e-9):
        raise ValueError("the Jacobi method is defined only for symmetric matrices")

    a: Matrix = [list(row) for row in matrix]
    basis = identity(size)

    for _ in range(max_sweeps):
        off_diagonal = math.sqrt(
            sum(a[i][j] * a[i][j] for i in range(size) for j in range(size) if i != j)
        )
        if off_diagonal <= tolerance:
            break
        for p in range(size - 1):
            for q in range(p + 1, size):
                if abs(a[p][q]) <= tolerance:
                    continue
                theta = (a[q][q] - a[p][p]) / (2.0 * a[p][q])
                sign = 1.0 if theta >= 0.0 else -1.0
                t = sign / (abs(theta) + math.sqrt(theta * theta + 1.0))
                cos = 1.0 / math.sqrt(t * t + 1.0)
                sin = t * cos

                for k in range(size):
                    a_kp, a_kq = a[k][p], a[k][q]
                    a[k][p] = cos * a_kp - sin * a_kq
                    a[k][q] = sin * a_kp + cos * a_kq
                for k in range(size):
                    a_pk, a_qk = a[p][k], a[q][k]
                    a[p][k] = cos * a_pk - sin * a_qk
                    a[q][k] = sin * a_pk + cos * a_qk
                for k in range(size):
                    v_kp, v_kq = basis[k][p], basis[k][q]
                    basis[k][p] = cos * v_kp - sin * v_kq
                    basis[k][q] = sin * v_kp + cos * v_kq

    eigenvalues = tuple(a[i][i] for i in range(size))
    return eigenvalues, basis


def matrix_vector(matrix: Sequence[Sequence[float]], vector: Sequence[float]) -> tuple[float, ...]:
    return tuple(sum(row[j] * vector[j] for j in range(len(vector))) for row in matrix)


def transpose_matrix_vector(
    matrix: Sequence[Sequence[float]], vector: Sequence[float]
) -> tuple[float, ...]:
    size = len(matrix)
    return tuple(sum(matrix[i][j] * vector[i] for i in range(size)) for j in range(size))
