from dramatiq import Worker
from dramatiq.brokers.stub import StubBroker

from kora.worker.broker import broker
from kora.worker.tasks import ping


def test_broker_de_test_est_en_memoire() -> None:
    assert isinstance(broker, StubBroker)


def test_tache_ping_est_executee_sans_echec() -> None:
    assert isinstance(broker, StubBroker)
    broker.flush_all()
    ping.send("phase-0")

    worker = Worker(broker, worker_timeout=100)
    worker.start()
    try:
        broker.join(ping.queue_name, fail_fast=True)
        worker.join()
    finally:
        worker.stop()

    assert broker.dead_letters == []
