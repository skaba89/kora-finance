from sqlalchemy import text
from sqlalchemy.orm import Session

from kora.models.offers import CommercialOfferVersion


def test_catalogue_commercial_global_en_lecture_seule(db: Session) -> None:
    privileges = db.execute(
        text(
            """
            SELECT has_table_privilege('commercial_offer_versions', 'SELECT'),
                   has_table_privilege('commercial_offer_versions', 'INSERT'),
                   has_table_privilege('commercial_offer_versions', 'UPDATE'),
                   has_table_privilege('commercial_offer_versions', 'DELETE')
            """
        )
    ).one()
    assert tuple(privileges) == (True, False, False, False)


def test_identite_version_offre_est_composee() -> None:
    assert list(CommercialOfferVersion.__table__.primary_key.columns.keys()) == ["code", "version"]
