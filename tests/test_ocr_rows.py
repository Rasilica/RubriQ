import pytest

from submission.ocr_rows import MAX_OBSERVATIONS, OcrObservation, OcrRowsError, reconstruct_lines

H = 0.02


def obs(text, x, yc, w=0.1, *, confidence=0.9):
    return OcrObservation(text=text, confidence=confidence, box=(x, yc - H / 2, w, H))


def texts(lines):
    return [line.text for line in lines]


def test_two_column_table_with_title_and_header():
    observations = [
        obs("2026학년도 신입생과 2학년 재학생", 0.25, 0.3052, w=0.4),
        obs("모집 대상", 0.05, 0.30),
        obs("20명 내외", 0.25, 0.3448, w=0.2),
        obs("모집 인원", 0.05, 0.3402),
        obs("모집 기간", 0.05, 0.38),
        obs("2026년 9월 10일", 0.25, 0.3795, w=0.3),
        obs("구분", 0.05, 0.26),
        obs("내용", 0.25, 0.2605),
        obs("동아리 모집 안내", 0.3, 0.1, w=0.4),
    ]

    lines = reconstruct_lines(observations)

    assert texts(lines) == [
        "동아리 모집 안내",
        "구분 | 내용",
        "모집 대상 | 2026학년도 신입생과 2학년 재학생",
        "모집 인원 | 20명 내외",
        "모집 기간 | 2026년 9월 10일",
    ]
    assert lines[2].cells == ("모집 대상", "2026학년도 신입생과 2학년 재학생")


def test_small_gap_joins_with_space():
    lines = reconstruct_lines([obs("hello", 0.1, 0.5), obs("world", 0.215, 0.5)])

    assert texts(lines) == ["hello world"]


def test_skewed_row_is_grouped():
    lines = reconstruct_lines([obs("a", 0.1, 0.500), obs("b", 0.22, 0.504), obs("c", 0.34, 0.508)])

    assert len(lines) == 1


def test_close_but_distinct_rows_are_not_merged():
    lines = reconstruct_lines([obs("first", 0.1, 0.50), obs("second", 0.1, 0.53)])

    assert texts(lines) == ["first", "second"]


def test_empty_and_single():
    assert reconstruct_lines([]) == ()
    assert texts(reconstruct_lines([obs("only", 0.1, 0.5)])) == ["only"]


def test_cap_exceeded_raises_typed_error():
    many = [obs("x", 0.1, 0.5)] * (MAX_OBSERVATIONS + 1)

    with pytest.raises(OcrRowsError):
        reconstruct_lines(many)
    assert issubclass(OcrRowsError, ValueError)


def test_confidence_is_min_and_box_is_union():
    lines = reconstruct_lines(
        [
            obs("left", 0.1, 0.5, w=0.1, confidence=0.9),
            obs("right", 0.5, 0.505, w=0.2, confidence=0.4),
        ]
    )

    assert lines[0].confidence == 0.4
    x, y, w, h = lines[0].box
    assert x == pytest.approx(0.1)
    assert y == pytest.approx(0.49)
    assert w == pytest.approx(0.6)
    assert h == pytest.approx(0.025)


def test_input_order_does_not_matter_and_output_is_immutable():
    a = [obs("one", 0.1, 0.3), obs("two", 0.1, 0.4)]

    assert reconstruct_lines(a) == reconstruct_lines(list(reversed(a)))
    assert isinstance(reconstruct_lines(a), tuple)


def table_head():
    return [obs("모집 기간", 0.05, 0.30), obs("9월 10일", 0.25, 0.30, w=0.2)]


def test_label_centred_between_two_value_lines_becomes_one_row():
    observations = [
        *table_head(),
        obs("선발 및 면담", 0.05, 0.375),
        obs("서류 심사 후 선발", 0.25, 0.37, w=0.3, confidence=0.8),
        obs("면담: 9월 20일", 0.25, 0.40, w=0.3, confidence=0.6),
    ]

    lines = reconstruct_lines(observations)

    assert texts(lines) == [
        "모집 기간 | 9월 10일",
        "선발 및 면담 | 서류 심사 후 선발 면담: 9월 20일",
    ]
    assert lines[1].cells == ("선발 및 면담", "서류 심사 후 선발 면담: 9월 20일")
    assert lines[1].confidence == 0.6
    assert lines[1].box[1] == pytest.approx(0.36)
    assert lines[1].box[3] == pytest.approx(0.05)


def test_label_on_middle_of_three_value_lines_collects_all_in_order():
    observations = [
        *table_head(),
        obs("활동 안내", 0.05, 0.40),
        obs("매주 수요일", 0.25, 0.37, w=0.3),
        obs("학생회관 3층", 0.25, 0.40, w=0.3),
        obs("회비: 1만원", 0.25, 0.43, w=0.3),
    ]

    lines = reconstruct_lines(observations)

    assert texts(lines) == [
        "모집 기간 | 9월 10일",
        "활동 안내 | 매주 수요일 학생회관 3층 회비: 1만원",
    ]


def test_following_table_row_keeps_its_own_value():
    observations = [
        *table_head(),
        obs("활동 안내", 0.05, 0.40),
        obs("매주 수요일", 0.25, 0.37, w=0.3),
        obs("학생회관 3층", 0.25, 0.40, w=0.3),
        obs("문의", 0.05, 0.47),
        obs("02-000-0000", 0.25, 0.47, w=0.3),
    ]

    assert texts(reconstruct_lines(observations))[1:] == [
        "활동 안내 | 매주 수요일 학생회관 3층",
        "문의 | 02-000-0000",
    ]


def test_paragraph_below_table_and_title_above_are_not_merged():
    observations = [
        obs("동아리 안내", 0.3, 0.26, w=0.3),
        *table_head(),
        obs("문의", 0.05, 0.33),
        obs("02-000-0000", 0.25, 0.33, w=0.3),
        obs("위 내용은 변경될 수 있습니다", 0.05, 0.36, w=0.8),
        obs("자세한 내용은 공지를 확인하세요", 0.05, 0.39, w=0.8),
    ]

    assert texts(reconstruct_lines(observations)) == [
        "동아리 안내",
        "모집 기간 | 9월 10일",
        "문의 | 02-000-0000",
        "위 내용은 변경될 수 있습니다",
        "자세한 내용은 공지를 확인하세요",
    ]


def test_distant_value_aligned_line_is_not_merged():
    observations = [*table_head(), obs("멀리 있는 줄", 0.25, 0.60, w=0.3)]

    assert texts(reconstruct_lines(observations)) == ["모집 기간 | 9월 10일", "멀리 있는 줄"]
