from ingest.chunker import chunk


def test_spec02_ac1_document_is_chunked():
    assert chunk("hello")
