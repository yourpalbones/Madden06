"""Tiny dense linear algebra (stdlib only; matrices are at most ~22x22)."""

from __future__ import annotations


def solve(a: list[list[float]], b: list[float]) -> list[float]:
    """Solve a x = b by Gaussian elimination with partial pivoting."""
    n = len(a)
    m = [row[:] + [b[i]] for i, row in enumerate(a)]
    for col in range(n):
        pivot = max(range(col, n), key=lambda r: abs(m[r][col]))
        if abs(m[pivot][col]) < 1e-12:
            raise ValueError("Singular matrix")
        m[col], m[pivot] = m[pivot], m[col]
        inv = 1.0 / m[col][col]
        for r in range(col + 1, n):
            f = m[r][col] * inv
            if f:
                for c in range(col, n + 1):
                    m[r][c] -= f * m[col][c]
    x = [0.0] * n
    for r in range(n - 1, -1, -1):
        s = m[r][n] - sum(m[r][c] * x[c] for c in range(r + 1, n))
        x[r] = s / m[r][r]
    return x


def lstsq(x_rows: list[list[float]], y: list[float], ridge: float = 1e-9) -> list[float]:
    """Least squares via normal equations with a tiny ridge for stability."""
    k = len(x_rows[0])
    xtx = [[0.0] * k for _ in range(k)]
    xty = [0.0] * k
    for row, yi in zip(x_rows, y):
        for i in range(k):
            ri = row[i]
            xty[i] += ri * yi
            for j in range(i, k):
                xtx[i][j] += ri * row[j]
    for i in range(k):
        for j in range(i):
            xtx[i][j] = xtx[j][i]
        xtx[i][i] += ridge * max(1.0, xtx[i][i])
    return solve(xtx, xty)


def conditional_gaussian(
    cov: list[list[float]], known: list[int], unknown: list[int], known_dev: list[float]
) -> tuple[list[float], list[float]]:
    """Mean shift and variance of ``unknown`` given deviations of ``known``.

    Returns (mean_shift, conditional_variance) for each unknown index.
    """
    if not known:
        return [0.0] * len(unknown), [cov[u][u] for u in unknown]
    kk = [[cov[i][j] for j in known] for i in known]
    trace = sum(kk[i][i] for i in range(len(known))) or 1.0
    for i in range(len(known)):
        kk[i][i] += 1e-6 * trace
    alpha = solve(kk, known_dev)  # Σ_kk^-1 e_k
    shifts, variances = [], []
    for u in unknown:
        row = [cov[u][j] for j in known]
        shifts.append(sum(r * a for r, a in zip(row, alpha)))
        w = solve(kk, row)  # Σ_kk^-1 Σ_ku
        variances.append(max(0.0, cov[u][u] - sum(r * wi for r, wi in zip(row, w))))
    return shifts, variances
