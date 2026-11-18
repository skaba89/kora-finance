"""Envoi des documents de vente par email avec PDF en pièce jointe (4D-bis).

Recette : un envoi vise un document numéroté (facture ou avoir ÉMIS, devis
envoyé/accepté/refusé) ; le destinataire est l'adresse explicite de la demande,
sinon l'email figé de la fiche du tier ; sans l'un ni l'autre, refus clair.
Un brouillon n'a ni numéro ni PDF (409), une facture annulée ne part pas (409)
et un envoi déjà en file pour une facture annulée entre-temps est abandonné
dans le worker sans réessai (renvoyer une facture annulée serait trompeur).
Contrairement à la relance (4D), un même document peut être envoyé plusieurs
fois le même jour : chaque envoi est enregistré et journalisé. L'email est
composé depuis l'état persisté (adresse figée à la demande, PDF rendu depuis
les instantanés figés à l'émission) et porte le PDF en pièce jointe. Vérifie
aussi l'isolation RLS, les permissions (lecteur lit, ne sert pas), le journal
d'audit et le garde-fou comptable : aucun écriture générée par les envois.
"""

import uuid
from collections.abc import Callable, Iterator
from contextlib import contextmanager

from dramatiq import Worker
from fastapi.testclient import TestClient
from httpx2 import Response

from kora.core.config import get_settings
from kora.email.sender import OutgoingAttachment, OutgoingEmail, _mime
from kora.worker.broker import broker
from tests.conftest import CompanyFixture, Mailbox
from tests.test_sales import (
    Sales,
    _creer_tva,
    _dossier,
    _facture_brouillon,
)

MakeCompany = Callable[..., CompanyFixture]
TTC_FACTURE = 3_540_000  # lignes 4B : 3 000 000 HT + 540 000 TVA (18 %)


@contextmanager
def _worker_frais() -> Iterator[Mailbox]:
    """Worker démarré À LA DEMANDE : sur le StubBroker (file locale), la tâche
    en file est traitée dans la microseconde qui suit la mise en file — en
    production, la file Redis introduit un délai. Pour éprouver le comportement
    « l'état change entre la mise en file et le traitement » (annulation,
    changement de fiche), la mutation doit passer AVANT le démarrage du worker."""
    worker = Worker(broker, worker_timeout=50)
    worker.start()
    try:
        yield Mailbox(worker)
    finally:
        worker.stop()


class Emails:
    """Raccourcis d'appel à l'API envois de documents pour un dossier."""

    def __init__(self, client: TestClient, company: CompanyFixture) -> None:
        self.client = client
        self.company = company
        self.base = f"/api/v1/companies/{company.id}"

    def send(
        self,
        document_id: str,
        body: dict[str, object] | None = None,
        company: CompanyFixture | None = None,
        headers: dict[str, str] | None = None,
    ) -> Response:
        entetes = headers if headers is not None else (company or self.company).headers
        return self.client.post(
            f"{self.base}/sales/{document_id}/email", headers=entetes, json=body or {}
        )

    def list(self, document_id: str, company: CompanyFixture | None = None) -> Response:
        headers = (company or self.company).headers
        return self.client.get(f"{self.base}/sales/{document_id}/emails", headers=headers)


def _tier(
    client: TestClient, company: CompanyFixture, *, email: str | None = "client@exemple.gn"
) -> str:
    """Tier client avec (ou sans) adresse email."""
    response = client.post(
        f"/api/v1/companies/{company.id}/partners",
        headers=company.headers,
        json={
            "name": f"Client Document-{uuid.uuid4().hex[:6]}",
            "is_client": True,
            "tax_id": f"NIU{uuid.uuid4().hex[:10].upper()}",
            "rccm": f"RCCM-KN-2026-B-{uuid.uuid4().hex[:4].upper()}",
            "address": "Kaloum, Conakry",
            "email": email,
        },
    )
    assert response.status_code == 201, response.text
    partner_id: str = response.json()["id"]
    return partner_id


def _facture_emise(
    sales: Sales, client: TestClient, company: CompanyFixture, **overrides: object
) -> str:
    """Facture ÉMISE (numérotée, mentions figées) : envoyable par email."""
    tva = _creer_tva(client, company)
    overrides.setdefault("partner_id", _tier(client, company))
    invoice_id = _facture_brouillon(sales, tva, **overrides)
    body = sales.issue(invoice_id).json()
    assert body["document"]["status"] == "ISSUED", body
    return invoice_id


def test_envoi_facture_avec_pdf_en_piece_jointe(
    client: TestClient, make_company: MakeCompany, mailbox: Mailbox
) -> None:
    """Chemin heureux : l'envoi est enregistré (destinataire = fiche du tier),
    l'email part dans le worker avec le PDF conformé en pièce jointe."""
    company = _dossier(make_company)
    sales = Sales(client, company)
    emails = Emails(client, company)
    tier = _tier(client, company, email="facture-client@exemple.gn")
    invoice_id = _facture_emise(sales, client, company, partner_id=tier)

    response = emails.send(invoice_id, {"note": "Merci pour votre confiance."})
    assert response.status_code == 201, response.text
    body = response.json()
    assert body["email_queued"] is True
    envoi = body["email"]
    assert envoi["email_to"] == "facture-client@exemple.gn"
    assert envoi["note"] == "Merci pour votre confiance."
    assert envoi["document_id"] == invoice_id

    historique = emails.list(invoice_id).json()
    assert historique["total"] == 1
    assert historique["items"][0]["id"] == envoi["id"]

    sent = mailbox.deliver()
    assert len(sent) == 1
    email = sent[0]
    assert email.to == "facture-client@exemple.gn"
    assert "facture" in email.subject.lower()
    assert len(email.attachments) == 1
    (piece,) = email.attachments
    assert piece.filename.endswith(".pdf")
    assert piece.content()[:5] == b"%PDF-"


def test_destinataire_explicite_et_renvois_le_meme_jour(
    client: TestClient, make_company: MakeCompany
) -> None:
    """L'adresse explicite prime sur la fiche du tier ; contrairement à la
    relance (4D), plusieurs envois le même jour sont légitimes (le client
    redemande l'exemplaire)."""
    company = _dossier(make_company)
    sales = Sales(client, company)
    emails = Emails(client, company)
    invoice_id = _facture_emise(sales, client, company)

    premier = emails.send(invoice_id, {"to": "comptabilite@exemple.gn"})
    assert premier.status_code == 201, premier.text
    assert premier.json()["email"]["email_to"] == "comptabilite@exemple.gn"

    second = emails.send(invoice_id, {"to": "direction@exemple.gn"})
    assert second.status_code == 201, second.text
    assert second.json()["email"]["email_to"] == "direction@exemple.gn"

    historique = emails.list(invoice_id).json()
    assert historique["total"] == 2
    destinataires = {i["email_to"] for i in historique["items"]}
    assert destinataires == {"comptabilite@exemple.gn", "direction@exemple.gn"}


def test_refus_brouillon_et_facture_annulee(client: TestClient, make_company: MakeCompany) -> None:
    company = _dossier(make_company)
    sales = Sales(client, company)
    emails = Emails(client, company)
    brouillon = _facture_brouillon(sales)
    assert emails.send(brouillon).status_code == 409

    invoice_id = _facture_emise(sales, client, company)
    annulation = sales.cancel(invoice_id)
    assert annulation.status_code in (200, 201), annulation.text
    assert emails.send(invoice_id).status_code == 409


def test_tier_sans_email_et_sans_destinataire_refuse(
    client: TestClient, make_company: MakeCompany
) -> None:
    company = _dossier(make_company)
    sales = Sales(client, company)
    emails = Emails(client, company)
    tier = _tier(client, company, email=None)
    invoice_id = _facture_emise(sales, client, company, partner_id=tier)
    response = emails.send(invoice_id)
    assert response.status_code == 422, response.text
    assert "email" in response.json()["detail"].lower()


def test_isolation_entre_dossiers(client: TestClient, make_company: MakeCompany) -> None:
    mine = Sales(client, _dossier(make_company))
    theirs_company = _dossier(make_company)
    theirs = Sales(client, theirs_company)
    emails_mine = Emails(client, mine.company)
    emails_theirs = Emails(client, theirs_company)
    invoice_id = _facture_emise(mine, client, mine.company)
    invoice_theirs = _facture_emise(theirs, client, theirs_company)

    # Le document d'un autre dossier est invisible : 404 (la RLS ne le voit pas).
    assert emails_theirs.send(invoice_id).status_code == 404
    # L'historique d'un document étranger est vide de mon point de vue (aucune fuite).
    historique = emails_mine.list(invoice_theirs)
    assert historique.status_code == 200
    assert historique.json()["items"] == []
    assert historique.json()["total"] == 0


def test_lecteur_lit_mais_ne_sert_pas(
    client: TestClient, make_company: MakeCompany, make_user: Callable[..., object]
) -> None:
    company = _dossier(make_company)
    sales = Sales(client, company)
    lecteur = make_user()
    client.post(
        f"/api/v1/companies/{company.id}/members",
        headers=company.headers,
        json={"email": lecteur.email, "role": "PME_LECTEUR"},  # type: ignore[attr-defined]
    )
    invoice_id = _facture_emise(sales, client, company)
    entetes_lecteur = lecteur.headers(client)  # type: ignore[attr-defined]
    reponse = client.post(
        f"/api/v1/companies/{company.id}/sales/{invoice_id}/email",
        headers=entetes_lecteur,
        json={},
    )
    assert reponse.status_code == 403
    # La lecture de l'historique reste permise (sales:read).
    historique = client.get(
        f"/api/v1/companies/{company.id}/sales/{invoice_id}/emails", headers=entetes_lecteur
    )
    assert historique.status_code == 200


def test_facture_annulee_apres_mise_en_file_abandon_sans_reessai(
    client: TestClient, make_company: MakeCompany
) -> None:
    """Une facture annulée entre la mise en file et le traitement du worker :
    l'envoi est abandonné sans réessai — aucun email ne part (renvoyer une
    facture annulée serait trompeur). Le worker démarre après l'annulation :
    sur la file locale, la tâche serait sinon traitée avant (microseconde)."""
    company = _dossier(make_company)
    sales = Sales(client, company)
    emails = Emails(client, company)
    tier = _tier(client, company, email="annulee-client@exemple.gn")
    invoice_id = _facture_emise(sales, client, company, partner_id=tier)

    assert emails.send(invoice_id).status_code == 201
    annulation = sales.cancel(invoice_id)
    assert annulation.status_code in (200, 201), annulation.text

    with _worker_frais() as boite:
        sent = boite.deliver()
    assert [e.to for e in sent] == [], "un email est parti pour une facture annulée"


def test_email_compose_depuis_etat_persiste(client: TestClient, make_company: MakeCompany) -> None:
    """Adresse figée à la demande et PDF rendu depuis les instantanés : changer
    l'email du tier entre la mise en file et le traitement ne change rien.
    Le worker démarre après la mutation de la fiche (voir _worker_frais)."""
    company = _dossier(make_company)
    sales = Sales(client, company)
    emails = Emails(client, company)
    tier = _tier(client, company, email="original@exemple.gn")
    invoice_id = _facture_emise(sales, client, company, partner_id=tier)

    assert emails.send(invoice_id).status_code == 201
    # Le tier change d'email après la mise en file : l'envoi reste figé.
    patch = client.patch(
        f"/api/v1/companies/{company.id}/partners/{tier}",
        headers=company.headers,
        json={"email": "nouvelle-adresse@exemple.gn"},
    )
    assert patch.status_code == 200, patch.text

    with _worker_frais() as boite:
        sent = boite.deliver()
    assert len(sent) == 1
    assert sent[0].to == "original@exemple.gn"


def test_journalise_envoi(client: TestClient, make_company: MakeCompany) -> None:
    company = _dossier(make_company)
    sales = Sales(client, company)
    emails = Emails(client, company)
    invoice_id = _facture_emise(sales, client, company)
    assert emails.send(invoice_id, {"to": "client@exemple.gn"}).status_code == 201
    journal = client.get(
        f"/api/v1/companies/{company.id}/audit-events", headers=company.headers
    ).json()
    actions = [e["action"] for e in (journal["items"] if isinstance(journal, dict) else journal)]
    assert "sales_document.emailed" in actions


def test_les_envois_necrivent_jamais_en_comptabilite(
    client: TestClient, make_company: MakeCompany, mailbox: Mailbox
) -> None:
    """Garde-fou 4E : aucun chemin des envois ne génère d'écriture."""
    company = _dossier(make_company)
    sales = Sales(client, company)
    emails = Emails(client, company)
    invoice_id = _facture_emise(sales, client, company)
    assert emails.send(invoice_id).status_code == 201
    mailbox.deliver()
    entries = client.get(f"/api/v1/companies/{company.id}/entries", headers=company.headers)
    assert entries.status_code == 200, entries.text
    assert entries.json()["items"] == [], "des écritures sont apparues : envois → comptabilité"


def test_piece_jointe_mime_conforme() -> None:
    """La pièce jointe est correctement composée en MIME (base64, disposition
    attachment, nom de fichier porté)."""
    piece = OutgoingAttachment.from_bytes("fac-2026-00001.pdf", b"%PDF-test", "application/pdf")
    email = OutgoingEmail(
        to="client@exemple.gn",
        subject="Votre facture",
        text="Voir la pièce jointe.",
        html="<p>Voir la pièce jointe.</p>",
        attachments=(piece,),
    )
    mime = _mime(email, get_settings())
    pieces = [p for p in mime.iter_attachments()]
    assert len(pieces) == 1
    (joint,) = pieces
    assert joint.get_filename() == "fac-2026-00001.pdf"
    assert joint.get_content_disposition() == "attachment"
    charge = joint.get_payload(decode=True)
    assert charge == b"%PDF-test"
