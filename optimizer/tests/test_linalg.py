"""Приёмка численного ядра оптимизатора (задача 38).

Собственное разложение — единственное место поиска со своим численным
методом, и проверяется оно тождеством, а не тем, что CMA-ES куда-то сошёлся:
сошедшийся поиск при испорченном разложении выглядит точно так же.
"""

from __future__ import annotations

import math

import pytest

from optimizer.linalg import identity, jacobi_eigen, matrix_vector, symmetrize


def _reconstruct(eigenvalues, basis):
    size = len(eigenvalues)
    return [
        [
            sum(basis[i][k] * eigenvalues[k] * basis[j][k] for k in range(size))
            for j in range(size)
        ]
        for i in range(size)
    ]


def _assert_close(left, right, tolerance=1e-9) -> None:
    for i, row in enumerate(left):
        for j, value in enumerate(row):
            assert abs(value - right[i][j]) < tolerance, f"({i},{j}): {value} != {right[i][j]}"


def test_identity_decomposes_into_itself() -> None:
    eigenvalues, basis = jacobi_eigen(identity(4))
    assert all(abs(value - 1.0) < 1e-12 for value in eigenvalues)
    _assert_close(_reconstruct(eigenvalues, basis), identity(4))


def test_diagonal_matrix_keeps_its_diagonal_as_spectrum() -> None:
    matrix = [[2.0, 0.0, 0.0], [0.0, 5.0, 0.0], [0.0, 0.0, 0.25]]
    eigenvalues, basis = jacobi_eigen(matrix)

    assert sorted(eigenvalues) == pytest.approx([0.25, 2.0, 5.0])
    _assert_close(_reconstruct(eigenvalues, basis), matrix)


def test_dense_symmetric_matrix_reconstructs_exactly() -> None:
    """A = B·diag(d)·Bᵀ — то самое тождество, ради которого разложение и нужно."""

    matrix = [
        [4.0, 1.0, -2.0, 0.5],
        [1.0, 3.0, 0.75, -1.0],
        [-2.0, 0.75, 6.0, 2.0],
        [0.5, -1.0, 2.0, 5.0],
    ]
    eigenvalues, basis = jacobi_eigen(matrix)
    _assert_close(_reconstruct(eigenvalues, basis), matrix)


def test_eigenvectors_are_orthonormal() -> None:
    """Ортонормальность `B` несущая: CMA-ES сэмплирует как `B·D·z`, и
    неортогональный базис молча искривил бы распределение выборки."""

    matrix = [
        [4.0, 1.0, -2.0],
        [1.0, 3.0, 0.75],
        [-2.0, 0.75, 6.0],
    ]
    _, basis = jacobi_eigen(matrix)
    size = len(matrix)

    for p in range(size):
        for q in range(size):
            dot = sum(basis[i][p] * basis[i][q] for i in range(size))
            expected = 1.0 if p == q else 0.0
            assert abs(dot - expected) < 1e-10, f"({p},{q}) = {dot}"


def test_each_pair_satisfies_the_eigen_equation() -> None:
    """A·b = λ·b покомпонентно — проверка того, что d и столбцы B не разъехались."""

    matrix = [
        [2.0, -1.0, 0.0],
        [-1.0, 2.0, -1.0],
        [0.0, -1.0, 2.0],
    ]
    eigenvalues, basis = jacobi_eigen(matrix)
    size = len(matrix)

    for k in range(size):
        vector = [basis[i][k] for i in range(size)]
        product = matrix_vector(matrix, vector)
        for i in range(size):
            assert abs(product[i] - eigenvalues[k] * vector[i]) < 1e-9


def test_positive_definite_matrix_has_positive_spectrum() -> None:
    """CMA-ES берёт sqrt(d): отрицательное собственное значение означает
    потерю положительной определённости, и поиск обязан это заметить."""

    matrix = [[2.0, 0.5], [0.5, 1.0]]
    eigenvalues, _ = jacobi_eigen(matrix)
    assert all(value > 0.0 for value in eigenvalues)
    assert all(math.sqrt(value) > 0.0 for value in eigenvalues)


def test_ten_by_ten_matrix_is_handled() -> None:
    """Потолок θ — 10 параметров, значит ковариация бывает 10×10."""

    size = 10
    matrix = [
        [float(size) if i == j else 1.0 / (1.0 + abs(i - j)) for j in range(size)]
        for i in range(size)
    ]
    eigenvalues, basis = jacobi_eigen(matrix)
    _assert_close(_reconstruct(eigenvalues, basis), matrix, tolerance=1e-8)
    assert all(value > 0.0 for value in eigenvalues)


def test_asymmetric_matrix_is_rejected() -> None:
    """Моков нет: несимметричную матрицу метод не «почти» раскладывает,
    а отказывается принимать."""

    with pytest.raises(ValueError):
        jacobi_eigen([[1.0, 2.0], [3.0, 4.0]])


def test_non_square_matrix_is_rejected() -> None:
    with pytest.raises(ValueError):
        jacobi_eigen([[1.0, 2.0, 3.0], [2.0, 4.0, 5.0]])


def test_empty_matrix_is_rejected() -> None:
    with pytest.raises(ValueError):
        jacobi_eigen([])


def test_symmetrize_removes_accumulated_asymmetry() -> None:
    """Дрейф порядка 1e-17 накапливается в обновлении ковариации; после
    симметризации матрица снова в классе, где разложение определено."""

    drifted = [[1.0, 0.5 + 1e-16], [0.5, 2.0]]
    fixed = symmetrize(drifted)

    assert fixed[0][1] == fixed[1][0]
    eigenvalues, basis = jacobi_eigen(fixed)
    _assert_close(_reconstruct(eigenvalues, basis), fixed)
