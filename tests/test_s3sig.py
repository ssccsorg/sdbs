"""
SigV4 signer pinned against the published AWS vectors.

Two vectors keep the signer honest. The header-signing case is the
``get-vanilla`` request from the AWS SigV4 test suite, and the presign case is
the worked example from the S3 documentation. Together they cover the
canonical request, the string to sign, the signing key, and the signature, so a
wrong encoding fails here rather than at deploy time.
"""

from __future__ import annotations

import pytest

from sdb_s3 import signer as s3sig

# get-vanilla, from the AWS SigV4 test suite.
VANILLA_ACCESS_KEY = "AKIDEXAMPLE"
VANILLA_SECRET_KEY = "wJalrXUtnFEMI/K7MDENG+bPxRfiCYEXAMPLEKEY"
VANILLA_AMZ_DATE = "20150830T123600Z"
VANILLA_SCOPE = "20150830/us-east-1/service/aws4_request"
VANILLA_CANONICAL_REQUEST = (
    "GET\n"
    "/\n"
    "\n"
    "host:example.amazonaws.com\n"
    "x-amz-date:20150830T123600Z\n"
    "\n"
    "host;x-amz-date\n"
    "e3b0c44298fc1c149afbf4c8996fb92427ae41e4649b934ca495991b7852b855"
)
VANILLA_STRING_TO_SIGN = (
    "AWS4-HMAC-SHA256\n"
    "20150830T123600Z\n"
    "20150830/us-east-1/service/aws4_request\n"
    "bb579772317eb040ac9ed261061d46c1f17a8133879d6129b6e1c25292927e63"
)
VANILLA_SIGNATURE = (
    "5fa00fa31553b73ebf1942676e86291e8372ff2a2260956d9b8aae1d763fbf31"
)
VANILLA_AUTHORIZATION = (
    "AWS4-HMAC-SHA256 Credential=AKIDEXAMPLE/20150830/us-east-1/service/aws4_request, "
    "SignedHeaders=host;x-amz-date, "
    "Signature=5fa00fa31553b73ebf1942676e86291e8372ff2a2260956d9b8aae1d763fbf31"
)

# Presigned GET from the S3 documentation.
PRESIGN_URL = (
    "https://examplebucket.s3.amazonaws.com/test.txt"
    "?X-Amz-Algorithm=AWS4-HMAC-SHA256"
    "&X-Amz-Credential=AKIAIOSFODNN7EXAMPLE%2F20130524%2Fus-east-1%2Fs3%2Faws4_request"
    "&X-Amz-Date=20130524T000000Z"
    "&X-Amz-Expires=86400"
    "&X-Amz-SignedHeaders=host"
    "&X-Amz-Signature=aeeed9bbccd4d02ee5c0109b86d86835f995330da4c265957d157751f604d404"
)


class TestHeaderSigningVector:
    def test_empty_payload_hash(self) -> None:
        assert s3sig.empty_payload_hash() == (
            "e3b0c44298fc1c149afbf4c8996fb92427ae41e4649b934ca495991b7852b855"
        )

    def test_canonical_request_matches_the_suite(self) -> None:
        request, signed = s3sig.canonical_request(
            "GET",
            "/",
            {},
            {"host": "example.amazonaws.com", "x-amz-date": VANILLA_AMZ_DATE},
            s3sig.empty_payload_hash(),
        )
        assert request == VANILLA_CANONICAL_REQUEST
        assert signed == "host;x-amz-date"

    def test_string_to_sign_matches_the_suite(self) -> None:
        string = s3sig.string_to_sign(
            VANILLA_AMZ_DATE, VANILLA_SCOPE, VANILLA_CANONICAL_REQUEST
        )
        assert string == VANILLA_STRING_TO_SIGN

    def test_signature_matches_the_suite(self) -> None:
        key = s3sig.signing_key(
            VANILLA_SECRET_KEY, VANILLA_AMZ_DATE, "us-east-1", "service"
        )
        signature = s3sig.sign_string(
            key, s3sig.string_to_sign(VANILLA_AMZ_DATE, VANILLA_SCOPE, VANILLA_CANONICAL_REQUEST)
        )
        assert signature == VANILLA_SIGNATURE

    def test_authorization_matches_the_suite(self) -> None:
        key = s3sig.signing_key(
            VANILLA_SECRET_KEY, VANILLA_AMZ_DATE, "us-east-1", "service"
        )
        signature = s3sig.sign_string(
            key, s3sig.string_to_sign(VANILLA_AMZ_DATE, VANILLA_SCOPE, VANILLA_CANONICAL_REQUEST)
        )
        header = s3sig.authorization_header(
            VANILLA_ACCESS_KEY, VANILLA_SCOPE, "host;x-amz-date", signature
        )
        assert header == VANILLA_AUTHORIZATION


class TestPresignVector:
    def test_presigned_url_matches_the_documentation(self) -> None:
        url = s3sig.presigned_url(
            scheme="https",
            host="examplebucket.s3.amazonaws.com",
            path="/test.txt",
            params={},
            access_key="AKIAIOSFODNN7EXAMPLE",
            secret_key="wJalrXUtnFEMI/K7MDENG/bPxRfiCYEXAMPLEKEY",
            amz_date="20130524T000000Z",
            region="us-east-1",
            service="s3",
            expires=86400,
        )
        assert url == PRESIGN_URL

    def test_expires_outside_the_allowed_range_is_rejected(self) -> None:
        with pytest.raises(ValueError):
            s3sig.presigned_url(
                scheme="https",
                host="examplebucket.s3.amazonaws.com",
                path="/test.txt",
                params={},
                access_key="AKIAIOSFODNN7EXAMPLE",
                secret_key="wJalrXUtnFEMI/K7MDENG/bPxRfiCYEXAMPLEKEY",
                amz_date="20130524T000000Z",
                region="us-east-1",
                service="s3",
                expires=0,
            )


class TestCanonicalHelpers:
    def test_canonical_uri_encodes_a_space_and_keeps_separators(self) -> None:
        assert s3sig.canonical_uri("/bucket/a b/c.pdf") == "/bucket/a%20b/c.pdf"

    def test_canonical_query_sorts_and_encodes(self) -> None:
        query = s3sig.canonical_query({"b": "2", "a": "1/2"})
        assert query == "a=1%2F2&b=2"

    def test_canonical_headers_trim_and_collapse(self) -> None:
        block, signed = s3sig.canonical_headers({"X-Test": "  a   b  "})
        assert block == "x-test:a b\n"
        assert signed == "x-test"
