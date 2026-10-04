"""
The s3 deploy plugin.

An external tool, unrelated to sdbs: it reads one JSON request on stdin, uploads
the named artifact directory to an S3-compatible object store, and writes one
JSON result on stdout. The store endpoint, region, and credentials come from the
environment, so nothing secret crosses the request.
"""

from .client import S3Client, S3Error
from .signer import MAX_PRESIGN_EXPIRES

__all__ = ["S3Client", "S3Error", "MAX_PRESIGN_EXPIRES"]
