import io
import json
import sys

import pytest

from cookbook_shelf.cli import main
from cookbook_shelf.demo import DemoTransport


@pytest.mark.parametrize("json_output", [False, True])
def test_unicode_recipe_survives_windows_pipe_encoding(monkeypatch, json_output):
    original = DemoTransport.read

    def read_unicode(self, url):
        document = original(self, url)
        document.html = document.html.replace("Spring bowl", "Kōdai bowl")
        return document

    monkeypatch.setattr(DemoTransport, "read", read_unicode)
    raw = io.BytesIO()
    pipe = io.TextIOWrapper(raw, encoding="cp1252")
    monkeypatch.setattr(sys, "stdout", pipe)
    args = ["--demo"] + (["--json"] if json_output else []) + ["search", "--ingredient", "edamame"]
    assert main(args) == 0
    pipe.flush()
    text = raw.getvalue().decode("utf-8")
    assert "Kōdai bowl" in text
    if json_output:
        assert json.loads(text)["items"][0]["title"] == "Kōdai bowl"
