from datetime import datetime, timedelta, timezone

import pytest

from services.sampling import (
    choose_spacing_mi,
    from_geojson_coords,
    generate_checkpoints,
    haversine_mi,
)

DEP = datetime(2026, 10, 12, 8, 0, tzinfo=timezone.utc)
LINE = [(0.0, 0.0), (0.0, 1.0), (0.0, 2.0), (0.0, 3.0)]  # along the equator


def test_haversine_one_degree_at_equator():
    assert haversine_mi((0, 0), (0, 1)) == pytest.approx(69.09, abs=0.1)


def test_from_geojson_swaps_axes():
    assert from_geojson_coords([[36.8, -1.3], [37.0, -1.2]]) == [(-1.3, 36.8), (-1.2, 37.0)]


@pytest.mark.parametrize("miles,expected", [
    (5, 10), (149.9, 10), (150, 25), (500, 25), (500.1, 50), (2800, 50),
])
def test_adaptive_spacing(miles, expected):
    assert choose_spacing_mi(miles) == expected


def test_checkpoints_start_at_origin_end_at_destination():
    cps = generate_checkpoints(LINE, DEP, total_distance_mi=100, total_duration_s=7200)
    assert cps[0].distance_mi == 0 and cps[0].eta == DEP
    assert cps[-1].distance_mi == 100
    assert cps[-1].eta == DEP + timedelta(seconds=7200)
    assert (cps[0].lat, cps[0].lon) == (0.0, 0.0)
    assert cps[-1].lon == pytest.approx(3.0)


def test_spacing_and_count_for_short_route():
    cps = generate_checkpoints(LINE, DEP, total_distance_mi=100, total_duration_s=7200)
    assert [c.distance_mi for c in cps] == [0, 10, 20, 30, 40, 50, 60, 70, 80, 90, 100]
    assert [c.index for c in cps] == list(range(11))


def test_medium_route_uses_25_mile_spacing():
    cps = generate_checkpoints(LINE, DEP, total_distance_mi=200, total_duration_s=7200)
    assert [c.distance_mi for c in cps] == [0, 25, 50, 75, 100, 125, 150, 175, 200]


def test_constant_speed_eta_is_linear():
    cps = generate_checkpoints(LINE, DEP, total_distance_mi=100, total_duration_s=7200)
    assert cps[1].elapsed_s == pytest.approx(720)  # 10 of 100 miles
    assert cps[5].elapsed_s == pytest.approx(3600)


def test_segment_durations_give_realistic_etas():
    coords = [(0, 0), (0, 1), (0, 2)]  # two equal-length segments
    cps = generate_checkpoints(
        coords, DEP, total_distance_mi=100, segment_durations_s=[1000, 3000], spacing_mi=50
    )
    assert [c.distance_mi for c in cps] == [0, 50, 100]
    assert [round(c.elapsed_s) for c in cps] == [0, 1000, 4000]


def test_segment_durations_scaled_to_reported_total():
    coords = [(0, 0), (0, 1), (0, 2)]
    cps = generate_checkpoints(
        coords, DEP, total_distance_mi=100, total_duration_s=8000,
        segment_durations_s=[1000, 3000], spacing_mi=50,
    )
    assert [round(c.elapsed_s) for c in cps] == [0, 2000, 8000]


def test_position_is_interpolated_along_route():
    cps = generate_checkpoints(LINE, DEP, total_distance_mi=100, total_duration_s=7200, spacing_mi=50)
    assert cps[1].lon == pytest.approx(1.5, abs=0.01) and cps[1].lat == pytest.approx(0)


def test_route_shorter_than_spacing_gets_origin_and_destination():
    cps = generate_checkpoints([(0, 0), (0, 0.05)], DEP, total_duration_s=600)
    assert len(cps) == 2


def test_checkpoint_too_close_to_destination_is_dropped():
    cps = generate_checkpoints(LINE, DEP, total_distance_mi=100, total_duration_s=7200, spacing_mi=45)
    assert [c.distance_mi for c in cps] == [0, 45, 100]  # 90 is within 25% of spacing of the end


def test_checkpoint_distances_strictly_increase():
    cps = generate_checkpoints(LINE, DEP, total_distance_mi=2800, total_duration_s=10_000)
    ds = [c.distance_mi for c in cps]
    assert ds == sorted(set(ds)) and ds[1] == 50


def test_duplicate_consecutive_points_are_ok():
    coords = [(0, 0), (0, 0), (0, 1), (0, 1), (0, 2)]
    cps = generate_checkpoints(coords, DEP, total_duration_s=3600, spacing_mi=50)
    assert cps[-1].distance_mi == pytest.approx(haversine_mi((0, 0), (0, 2)))


def test_validation():
    with pytest.raises(ValueError):
        generate_checkpoints(LINE, datetime(2026, 10, 12, 8, 0), total_duration_s=100)  # naive
    with pytest.raises(ValueError):
        generate_checkpoints([(0, 0)], DEP, total_duration_s=100)
    with pytest.raises(ValueError):
        generate_checkpoints([(1, 1), (1, 1)], DEP, total_duration_s=100)
    with pytest.raises(ValueError):
        generate_checkpoints(LINE, DEP)  # no duration info
    with pytest.raises(ValueError):
        generate_checkpoints(LINE, DEP, segment_durations_s=[1, 2])  # wrong length
