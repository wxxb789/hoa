import io
import json
import math
from urllib.error import HTTPError, URLError

import pytest

from evals import run_skill_distinctiveness as distinct


@pytest.fixture
def inputs(tmp_path, monkeypatch):
    def no_network(*args):
        pytest.fail("unexpected network access")

    monkeypatch.setattr(distinct, "build_opener", no_network)
    skills = tmp_path / "skills"
    for name, description, visibility in [
        ("alpha", "shared red", ""),
        ("beta", ">-\n  shared\n  blue", ""),
        ("hidden", "private amber", "disable-model-invocation: true\n"),
    ]:
        folder = skills / name
        folder.mkdir(parents=True)
        (folder / "SKILL.md").write_text(
            f"---\nname: {name}\ndescription: {description}\n{visibility}---\n# Body is not indexed\n",
            encoding="utf-8",
        )
    queries = tmp_path / "queries.jsonl"
    samples = [
        ("rank", "blue blue", "beta", "en"),
        ("tie", "shared", "beta", "en"),
        ("zero", "\u6ca1\u6709\u5339\u914d\u9879", "alpha", "zh-CN"),
        ("hidden", "private", "hidden", "en"),
        ("none", "inapplicable", "none", "en"),
        ("outside", "outside", "not-a-skill", "en"),
    ]
    queries.write_text("".join(json.dumps(dict(id=qid, text=text, skill=skill, lang=lang)) + "\n"
                               for qid, text, skill, lang in samples), encoding="utf-8")
    output = tmp_path / "reports" / "sample"

    def run(*extra):
        return distinct.main([
            "--skills-dir", str(skills), "--queries", str(queries), "--output", str(output), *extra,
        ])

    return run, output


def report(output):
    return json.loads(output.with_suffix(".json").read_text(encoding="utf-8"))


def test_offline_rankings_and_cosine(inputs):
    run, output = inputs
    assert run() == 0
    result = report(output)
    rows = result["bm25_queries"]
    assert rows["rank"]["top1"] == "beta"
    assert rows["rank"]["margin"] == pytest.approx(math.log1p(2.5 / 1.5))
    assert rows["tie"]["top1"] == "alpha"
    assert rows["tie"]["top_ties"] == 2
    assert rows["tie"]["rank"] == 2
    assert rows["tie"]["margin"] == 0
    assert result["bm25"]["en"]["n"] == 3
    assert result["bm25"]["en"]["top1"] == pytest.approx(2 / 3)
    assert result["bm25"]["en"]["mrr"] == pytest.approx(5 / 6)
    assert rows["hidden"]["top1"] == "hidden"
    assert rows["none"]["rank"] is rows["outside"]["rank"] is None
    assert rows["zero"]["top_ties"] == 3
    zh = result["bm25"]["zh"]
    assert zh["top1"] == zh["mrr"] == zh["all_zero"] == 1
    assert zh["positive_top1"] == zh["positive_mrr"] == zh["mean_margin"] == 0
    similarity = (1 + math.log(4 / 3)) ** 2
    expected_cosine = similarity / (similarity + 2 * (1 + math.log(4 / 2)) ** 2)
    assert result["nearest_neighbors"]["alpha"] == dict(skill="beta", cosine=pytest.approx(expected_cosine))
    assert result["nearest_neighbors"]["hidden"] == dict(skill="alpha", cosine=0)
    assert result["llm"] is None
    assert output.with_suffix(".md").is_file()


@pytest.mark.parametrize("overrides", [{"beta": "shared green"}, {"missing": "green"}, {"beta": ""}])
def test_description_overrides(inputs, tmp_path, overrides):
    run, output = inputs
    draft = tmp_path / "draft.json"
    draft.write_text(json.dumps(overrides), encoding="utf-8")
    if overrides == {"beta": "shared green"}:
        assert run("--descriptions", str(draft)) == 0
        result = report(output)
        assert result["bm25_queries"]["rank"]["top1_score"] == 0
        assert result["skills"]["beta"]["description"] == "shared green"
        assert result["skills"]["hidden"]["hidden"]
    else:
        with pytest.raises(SystemExit) as error:
            run("--descriptions", str(draft))
        assert error.value.code == 2
        assert not output.with_suffix(".json").exists()


@pytest.mark.parametrize("use_pi", [False, True])
def test_llm_orders_parsing_and_no_credential_leak(inputs, tmp_path, monkeypatch, capsys, use_pi):
    run, output = inputs
    key = "test-key-not-for-output"
    for suffix in ("BASE_URL", "MODEL", "API_KEY"):
        monkeypatch.delenv(f"DISTINCTIVENESS_{suffix}", raising=False)
    args = []
    if use_pi:
        models = tmp_path / "models.json"
        models.write_text(json.dumps({"providers": {"stub": {
            "baseUrl": "https://example.invalid/v1", "apiKey": "${STUB_SECRET}", "models": [{"id": "test-model"}],
        }}}), encoding="utf-8")
        monkeypatch.setenv("STUB_SECRET", key)
        args = ["--pi-models", str(models), "--pi-provider", "stub"]
    else:
        monkeypatch.setenv("DISTINCTIVENESS_BASE_URL", "https://example.invalid/v1/")
        monkeypatch.setenv("DISTINCTIVENESS_API_KEY", key)
        monkeypatch.setenv("DISTINCTIVENESS_MODEL", "test-model")
    sent = []

    class Stub:
        def open(self, request, timeout):
            payload = json.loads(request.data)
            prompt, query = (message["content"] for message in payload["messages"])
            order = tuple(line.partition(":")[0] for line in prompt.splitlines()
                          if line.startswith(("alpha:", "beta:", "hidden:")))
            sent.append((order, query))
            assert request.full_url == "https://example.invalid/v1/chat/completions"
            assert request.get_header("Authorization") == f"Bearer {key}"
            assert payload["model"] == "test-model"
            assert key not in request.data.decode("utf-8")
            if query == "blue blue":
                content = '```json\n{"best":"beta","top3":["beta","alpha","none"]}\n```'
            elif query == "inapplicable":
                content = (json.dumps(dict(best=key, top3=[key, "alpha", "beta"])) if '"top3"' in prompt
                           else '{"best":"none","backups":["alpha","beta"]}')
            elif query == "shared":
                content = ('{"best":"beta","top3":["alpha","beta","none"]}' if '"top3"' in prompt
                           else '{"best":"beta","backups":["alpha","alpha"]}')
            else:
                raise URLError(key)
            return io.BytesIO(json.dumps({"choices": [{"message": {"content": content}}]}).encode())

    monkeypatch.setattr(distinct, "build_opener", lambda *args: Stub())
    assert run("--llm", "--orders", "2", *args) == 0
    result = report(output)["llm"]
    assert {order for order, _ in sent} == {("alpha", "beta"), ("beta", "alpha")}
    assert {query for _, query in sent} == {"blue blue", "shared", "inapplicable", "\u6ca1\u6709\u5339\u914d\u9879"}
    for order in result["orders"]:
        assert order["valid"] == 2
        assert order["n"] == 4
        assert order["predictions"]["none"] == dict(top3=["none", "alpha", "beta"], recovered=True)
        assert order["predictions"]["tie"] == dict(error="invalid_ranking")
        assert order["predictions"]["zero"] == dict(error="transport")
    assert result["average"] == dict(top1=0.5, top3=0.5, none_precision=1.0, none_recall=1.0)
    captured = capsys.readouterr()
    for text in (captured.out, captured.err, *(output.with_suffix(s).read_text(encoding="utf-8") for s in (".md", ".json"))):
        assert key not in text


def test_llm_http_failure_does_not_expose_provider_error(inputs, monkeypatch, capsys):
    run, output = inputs
    key = "test-key-not-for-output"
    monkeypatch.setenv("DISTINCTIVENESS_API_KEY", key)
    monkeypatch.setenv("DISTINCTIVENESS_MODEL", "test-model")
    monkeypatch.setenv("DISTINCTIVENESS_BASE_URL", "https://example.invalid/v1")

    class Stub:
        def open(self, request, timeout):
            raise HTTPError(request.full_url, 401, key, {}, io.BytesIO(key.encode()))

    monkeypatch.setattr(distinct, "build_opener", lambda *args: Stub())
    with pytest.raises(SystemExit) as error:
        run("--llm")
    assert error.value.code == 2
    captured = capsys.readouterr()
    assert "401" in captured.err
    assert key not in captured.out + captured.err
    assert not output.with_suffix(".json").exists()
