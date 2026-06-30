"""Pure transmission domain — config, routing, ack-chain ledger."""

import pytest

from app import transmission as tx


# -- config ------------------------------------------------------------------
def test_config_requires_account_cert_and_no_direct_hc():
    errs = {e["rule"] for e in tx.validate_esg_config(
        {"account_type": "bogus", "hc_direct_endpoint": "as2://hc"})}
    assert {"account_type_invalid", "x509_certificate_required",
            "no_direct_hc_endpoint"} <= errs


def test_production_locked_until_test_round_trip():
    cfg = tx.build_esg_config({"account_type": "AS2",
                               "x509_certificate": "PEM"})
    assert cfg["production_enabled"] is False
    assert tx.can_transmit_production(cfg)[0] is False
    cfg = tx.complete_test_round_trip(cfg)
    assert cfg["production_enabled"] is True
    assert tx.can_transmit_production(cfg)[0] is True


def test_incomplete_round_trip_keeps_production_locked():
    cfg = tx.build_esg_config({"account_type": "AS2", "x509_certificate": "P"})
    cfg = tx.complete_test_round_trip(cfg, {"hc_ack_received": False})
    assert cfg["production_enabled"] is False


# -- size routing ------------------------------------------------------------
def test_size_routing_gateway_vs_media():
    assert tx.evaluate_size_routing(8)["route"] == "gateway"
    over = tx.evaluate_size_routing(12)
    assert over["route"] == "physical_media" and over["shipping_instructions"]


def test_congestion_window_5_to_10gb():
    assert tx.evaluate_size_routing(7)["congestion"]["offer"] is True
    assert tx.evaluate_size_routing(2)["congestion"]["offer"] is False


# -- ack-chain ledger --------------------------------------------------------
def test_submit_dispatches_sent():
    led = tx.TransmissionLedger("e1")
    rec = led.submit({"sequence": "0000", "size_gb": 1})
    assert rec["state"] == "SENT" and rec["message_id"] == "MSG-e1-0000"


def test_second_submit_is_queued_one_at_a_time():
    led = tx.TransmissionLedger("e1")
    led.submit({"sequence": "0000", "size_gb": 1})
    rec2 = led.submit({"sequence": "0001", "size_gb": 1})
    assert rec2["state"] == "QUEUED" and rec2["queued_behind"] == "0000"


def test_full_ack_chain_and_dequeue():
    led = tx.TransmissionLedger("e1")
    led.submit({"sequence": "0000", "size_gb": 1})
    led.submit({"sequence": "0001", "size_gb": 1})   # queued
    led.receive_mdn("0000")
    led.receive_fda_ack("0000", "CORE-1")
    assert led._find("0000")["state"] == "FDA_ACK"
    led.receive_hc_ack("CORE-1")
    assert led._find("0000")["state"] == "RECEIVED_BY_HC"
    # the queued sequence is now dispatched
    assert led._find("0001")["state"] == "SENT"


def test_duplicate_sequence_raises():
    led = tx.TransmissionLedger("e1")
    led.submit({"sequence": "0000", "size_gb": 1})
    with pytest.raises(tx.TransmissionError):
        led.submit({"sequence": "0000", "size_gb": 1})


def test_production_submit_blocked_without_round_trip():
    cfg = tx.build_esg_config({"account_type": "AS2", "x509_certificate": "P"})
    led = tx.TransmissionLedger("e1", cfg)
    with pytest.raises(tx.ProductionBlockedError):
        led.submit({"sequence": "0000", "size_gb": 1}, production=True)


def test_transport_rejection_frees_slot():
    led = tx.TransmissionLedger("e1")
    led.submit({"sequence": "0000", "size_gb": 1})
    led.receive_mdn("0000")
    led.receive_fda_ack("0000", "CORE-1", transport_rejected=True)
    assert led._find("0000")["state"] == "REJECTED"
