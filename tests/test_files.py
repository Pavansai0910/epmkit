"""File transfer through the interop (migration) API."""

import json

import pytest

from epmkit import EPMError

INTEROP = "/interop/rest/11.1.2.3.600/applicationsnapshots"


def test_upload_sends_q_param_and_raw_bytes(client, mock_api, tmp_path):
    src = tmp_path / "actuals_nov.csv"
    src.write_bytes(b"Account,Period,Amount\nRevenue,Nov,125000\n")
    route = mock_api.post(f"{INTEROP}/actuals_nov.csv/contents").respond(json={"status": 0})

    assert client.files.upload(src) == "actuals_nov.csv"

    request = route.calls.last.request
    assert json.loads(request.url.params["q"]) == {"isFirst": True, "isLast": True, "chunkSize": 41}
    assert request.content == src.read_bytes()
    assert request.headers["Content-Type"] == "application/octet-stream"


def test_upload_splits_large_files_into_chunks(client, mock_api, tmp_path):
    src = tmp_path / "big.csv"
    src.write_bytes(b"0123456789")
    route = mock_api.post(f"{INTEROP}/big.csv/contents").respond(json={"status": 0})

    client.files.upload(src, chunk_size=6)

    sent = [(json.loads(c.request.url.params["q"]), c.request.content) for c in route.calls]
    assert sent == [
        ({"isFirst": True, "isLast": False, "chunkSize": 6}, b"012345"),
        ({"isFirst": False, "isLast": True, "chunkSize": 4}, b"6789"),
    ]


def test_upload_with_nonzero_status_raises(client, mock_api, tmp_path):
    src = tmp_path / "bad.csv"
    src.write_text("x")
    # The interop API reports failure inside an HTTP 200 body.
    mock_api.post(f"{INTEROP}/bad.csv/contents").respond(json={"status": 9, "details": "Disk quota exceeded"})

    with pytest.raises(EPMError, match="Disk quota exceeded"):
        client.files.upload(src)


def test_download_writes_file(client, mock_api, tmp_path):
    mock_api.get(f"{INTEROP}/report.csv/contents").respond(content=b"a,b\n1,2\n")

    target = client.files.download("report.csv", tmp_path)

    assert target == tmp_path / "report.csv"
    assert target.read_bytes() == b"a,b\n1,2\n"


def test_delete_hits_the_right_url(client, mock_api):
    route = mock_api.delete(f"{INTEROP}/old_actuals.csv").respond(json={"status": 0})

    client.files.delete("old_actuals.csv")

    assert route.call_count == 1
    assert route.calls.last.request.method == "DELETE"
