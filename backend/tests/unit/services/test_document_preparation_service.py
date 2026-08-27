from application.source.document_preparation_service import preparation_fingerprint


def test_document_preparation_fingerprint_tracks_source_and_analysis_versions():
    baseline = preparation_fingerprint(
        sha256="a" * 64,
        parser_version="source-runtime.v1",
        document_analysis_version="document-analysis.v1",
    )

    assert baseline == preparation_fingerprint(
        sha256="a" * 64,
        parser_version="source-runtime.v1",
        document_analysis_version="document-analysis.v1",
    )
    assert baseline != preparation_fingerprint(
        sha256="b" * 64,
        parser_version="source-runtime.v1",
        document_analysis_version="document-analysis.v1",
    )
    assert baseline != preparation_fingerprint(
        sha256="a" * 64,
        parser_version="source-runtime.v2",
        document_analysis_version="document-analysis.v1",
    )
