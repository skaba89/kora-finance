import uuid
from collections.abc import Callable
from datetime import date

import pytest
from sqlalchemy import Engine, select, text
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from kora.db.tenant import bind_tenant
from kora.models.licenses import CommercialLicensePeriod
from kora.models.offers import CommercialOfferVersion
from tests.conftest import CompanyFixture


def test_periodes_commerciales_en_lecture_seule(db: Session) -> None:
    privileges = db.execute(
        text(
            """
            SELECT has_table_privilege('commercial_license_periods', 'SELECT'),
                   has_table_privilege('commercial_license_periods', 'INSERT'),
                   has_table_privilege('commercial_license_periods', 'UPDATE'),
                   has_table_privilege('commercial_license_periods', 'DELETE')
            """
        )
    ).one()
    assert tuple(privileges) == (True, False, False, False)


def test_periodes_adjacentes_et_isolation(
    owner_engine: Engine, make_company: Callable[..., CompanyFixture]
) -> None:
    mine, theirs = make_company(), make_company()
    code = f"test-{uuid.uuid4().hex}"
    with Session(owner_engine) as session:
        bind_tenant(session, mine.id)
        session.add(CommercialOfferVersion(code=code, version=1, modules=["sales"]))
        session.flush()

        def period(start: date, end: date) -> CommercialLicensePeriod:
            return CommercialLicensePeriod(
                tenant_id=mine.id,
                offer_code=code,
                offer_version=1,
                kind="paid",
                starts_on=start,
                ends_on=end,
            )

        session.add(period(date(2026, 11, 1), date(2026, 12, 1)))
        session.add(period(date(2026, 12, 1), date(2027, 1, 1)))
        session.flush()
        savepoint = session.begin_nested()
        session.add(period(date(2026, 11, 15), date(2026, 12, 15)))
        with pytest.raises(IntegrityError, match="commercial_license_periods_no_overlap"):
            session.flush()
        savepoint.rollback()

        assert len(session.scalars(select(CommercialLicensePeriod)).all()) == 2
        bind_tenant(session, theirs.id)
        assert session.scalars(select(CommercialLicensePeriod)).all() == []
        bind_tenant(session, None)
        assert session.scalars(select(CommercialLicensePeriod)).all() == []
