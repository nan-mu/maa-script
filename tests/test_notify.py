from maa_runner.notify import TG_LIMIT, chunk_text


def test_short_text_is_single_chunk():
    assert chunk_text("hello") == ["hello"]


def test_over_limit_chunks_stay_within_4096():
    text = ("line\n" * 2000) + ("x" * 3000)
    chunks = chunk_text(text)
    assert len(chunks) > 1
    assert all(len(part) <= TG_LIMIT for part in chunks)
    assert "".join(chunks).replace("\n", "") == text.replace("\n", "")
