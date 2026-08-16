from __future__ import annotations

Matrix = tuple[tuple[int, ...], ...]

_UNIT: Matrix = ((1,),)


def is_prime(n: int) -> bool:
    if n < 2:
        return False
    if n % 2 == 0:
        return n == 2
    divisor = 3
    while divisor * divisor <= n:
        if n % divisor == 0:
            return False
        divisor += 2
    return True


def _quadratic_residues(q: int) -> set[int]:
    return {(x * x) % q for x in range(1, q)}


def _legendre(q: int, residues: set[int]) -> list[list[int]]:
    symbol: list[int] = []
    for value in range(q):
        if value == 0:
            symbol.append(0)
        elif value in residues:
            symbol.append(1)
        else:
            symbol.append(-1)
    return [[symbol[(column - row) % q] for column in range(q)] for row in range(q)]


def _paley_first(order: int) -> Matrix:
    q = order - 1
    jacobsthal = _legendre(q, _quadratic_residues(q))
    rows: list[list[int]] = [[1] * order]
    for row in range(q):
        built = [1]
        for column in range(q):
            built.append(-1 if row == column else jacobsthal[row][column])
        rows.append(built)
    return tuple(tuple(row) for row in rows)


def _paley_second(order: int) -> Matrix:
    q = order // 2 - 1
    jacobsthal = _legendre(q, _quadratic_residues(q))
    size = q + 1
    core: list[list[int]] = [[0] * size for _ in range(size)]
    for column in range(1, size):
        core[0][column] = 1
        core[column][0] = 1
    for row in range(q):
        for column in range(q):
            core[row + 1][column + 1] = jacobsthal[row][column]
    blocks: list[list[int]] = []
    for row in range(size):
        upper: list[int] = []
        lower: list[int] = []
        for column in range(size):
            value = core[row][column]
            if value == 0:
                upper.extend((1, -1))
                lower.extend((-1, -1))
            elif value == 1:
                upper.extend((1, 1))
                lower.extend((1, -1))
            else:
                upper.extend((-1, -1))
                lower.extend((-1, 1))
        blocks.append(upper)
        blocks.append(lower)
    ordered = [blocks[2 * i] for i in range(size)] + [
        blocks[2 * i + 1] for i in range(size)
    ]
    return tuple(tuple(row) for row in ordered)


def _doubled(base: Matrix) -> Matrix:
    size = len(base)
    rows: list[tuple[int, ...]] = []
    for row in base:
        rows.append(tuple(row) + tuple(row))
    for row in base:
        rows.append(tuple(row) + tuple(-v for v in row))
    if len(rows) != 2 * size:
        raise ValueError("удвоение Сильвестра не дало матрицу двойного порядка")
    return tuple(rows)


def hadamard(order: int) -> Matrix:
    if order == 1:
        return _UNIT
    if order == 2:
        return ((1, 1), (1, -1))
    if order % 4 != 0:
        raise ValueError(
            f"порядок {order} не кратен четырём: матрицы Адамара такого "
            f"порядка не существует"
        )
    if is_prime(order - 1):
        return _paley_first(order)
    half = order // 2 - 1
    if is_prime(half) and half % 4 == 1:
        return _paley_second(order)
    if order % 2 == 0:
        return _doubled(hadamard(order // 2))
    raise ValueError(
        f"матрица Адамара порядка {order} не строится доступными "
        f"конструкциями (Пэли I, Пэли II, удвоение Сильвестра)"
    )


def is_hadamard(matrix: Matrix) -> bool:
    size = len(matrix)
    for row in matrix:
        if len(row) != size:
            raise ValueError("матрица Адамара не квадратна")
        if any(value not in (1, -1) for value in row):
            return False
    for first in range(size):
        for second in range(first + 1, size):
            product = sum(
                matrix[first][k] * matrix[second][k] for k in range(size)
            )
            if product != 0:
                return False
    return True


def normalized(matrix: Matrix) -> Matrix:
    flipped_columns = tuple(
        tuple(
            value * matrix[0][column]
            for column, value in enumerate(row)
        )
        for row in matrix
    )
    return tuple(
        tuple(value * flipped_columns[index][0] for value in row)
        for index, row in enumerate(flipped_columns)
    )
