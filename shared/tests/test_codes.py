from shared.taxonomy import CODE_DESCRIPTIONS, ErrorCode


def test_fourteen_codes():
    assert len(ErrorCode) == 14


def test_every_code_has_a_description():
    assert set(ErrorCode) == set(CODE_DESCRIPTIONS)
