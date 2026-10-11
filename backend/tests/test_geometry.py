import math

from services.geometry import _dist_to_segment, _project, simplify_path


def test_short_paths_returned_unchanged():
    assert simplify_path([]) == []
    assert simplify_path([(0, 0)]) == [(0, 0)]
    assert simplify_path([(0, 0), (1, 1)]) == [(0, 0), (1, 1)]


def test_collinear_points_collapse_to_endpoints():
    line = [(0.0, i * 0.01) for i in range(200)]
    assert simplify_path(line) == [line[0], line[-1]]


def test_corner_is_preserved():
    path = [(0.0, i * 0.01) for i in range(50)] + [(i * 0.01, 0.49) for i in range(1, 50)]
    out = simplify_path(path)
    assert (0.0, 0.49) in out and out[0] == path[0] and out[-1] == path[-1]
    assert len(out) <= 4


def test_small_wiggles_dropped_large_kept():
    # ~0.01 mi bump (below the 0.03 mi tolerance) vs ~1 mi bump
    small = [(0, 0), (0.0001, 0.5), (0, 1.0)]
    big = [(0, 0), (0.015, 0.5), (0, 1.0)]
    assert len(simplify_path(small)) == 2
    assert len(simplify_path(big)) == 3


def test_endpoints_always_kept_and_order_preserved():
    path = [(i * 0.001, (i % 7) * 0.003 + i * 0.01) for i in range(500)]
    out = simplify_path(path)
    assert out[0] == path[0] and out[-1] == path[-1]
    idx = [path.index(p) for p in out]
    assert idx == sorted(idx)


def test_max_points_enforced():
    zigzag = [((i % 2) * 0.01, i * 0.01) for i in range(400)]
    out = simplify_path(zigzag, tolerance_mi=0.001, max_points=60)
    assert len(out) <= 60


def test_every_original_point_stays_within_tolerance_of_result():
    path = [(0.05 * math.sin(i / 30), i * 0.01) for i in range(600)]
    tol = 0.05
    out = simplify_path(path, tolerance_mi=tol)
    assert len(out) < len(path) / 3

    pts = _project(path)  # same projection simplify_path used (it projects the full path)
    kept_idx = [path.index(p) for p in out]
    worst = 0.0
    for a, b in zip(kept_idx, kept_idx[1:]):
        for k in range(a, b + 1):
            worst = max(worst, _dist_to_segment(pts[k], pts[a], pts[b]))
    assert worst <= tol + 1e-9
