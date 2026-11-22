from sqlalchemy import inspect, text
from sqlalchemy.orm import Session

from kora.models.offers import CommercialOfferVersion


def test_catalogue_commercial_global_ajout_uniquement(db: Session) -> None:
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
    assert tuple(privileges) == (True, True, False, False)


def test_identite_version_offre_est_composee() -> None:
    keys = [column.key for column in inspect(CommercialOfferVersion).primary_key]
    assert keys == ["code", "version"]
