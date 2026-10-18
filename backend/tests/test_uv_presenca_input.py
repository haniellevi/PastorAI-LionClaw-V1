import pytest
from pydantic import ValidationError


def test_attendance_requires_typed_modality_and_explicit_revision():
    from app.routers.uv import PresencaInput
    from uuid import uuid4
    valid = dict(id=uuid4(),presente=True,modalidade='reposicao')
    assert PresencaInput(**valid).anterior_id is None
    for change in [dict(presente='true'),dict(modalidade='encontro'),dict(registrada_por=uuid4())]:
        with pytest.raises(ValidationError): PresencaInput(**(valid | change))
