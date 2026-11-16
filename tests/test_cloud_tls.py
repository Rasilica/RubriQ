import ssl
from unittest.mock import MagicMock, patch

import pytest

from submission.cloud_client import request_bytes
from submission.cloud_contracts import CloudError


def test_cloud_connection_has_explicit_verified_root_store():
    connection = MagicMock()
    connection.getresponse.return_value.status = 200
    connection.getresponse.return_value.read.return_value = b"{}"
    with patch("submission.cloud_client.HTTPSConnection", return_value=connection) as transport:
        result = request_bytes("billing-ai.doubleze.ro", "/api/v1/chat/completions", b"{}", {})
    assert result == b"{}"
    context = transport.call_args.kwargs["context"]
    assert isinstance(context, ssl.SSLContext)
    assert context.check_hostname
    assert context.verify_mode == ssl.CERT_REQUIRED
    assert context.cert_store_stats()["x509_ca"] > 0
    connection.request.assert_called_once()


def test_certificate_failure_is_distinct_and_never_retried(caplog):
    with patch("submission.cloud_client.HTTPSConnection") as transport:
        transport.return_value.request.side_effect = ssl.SSLCertVerificationError("private secret")
        with pytest.raises(CloudError, match="cloud_tls_failed"):
            request_bytes("billing-ai.doubleze.ro", "/api/v1/chat/completions", b"private", {})
    transport.assert_called_once()
    assert "private" not in caplog.text


def test_missing_system_roots_are_repaired_without_disabling_verification():
    context = ssl.SSLContext(ssl.PROTOCOL_TLS_CLIENT)
    assert context.cert_store_stats()["x509_ca"] == 0
    connection = MagicMock()
    connection.getresponse.return_value.status = 200
    connection.getresponse.return_value.read.return_value = b"{}"
    with (
        patch("submission.cloud_client.ssl.create_default_context", return_value=context),
        patch("submission.cloud_client.HTTPSConnection", return_value=connection),
    ):
        request_bytes("billing-ai.doubleze.ro", "/api/v1/chat/completions", b"{}", {})
    assert context.cert_store_stats()["x509_ca"] > 0
    assert context.check_hostname
    assert context.verify_mode == ssl.CERT_REQUIRED
