import os
from pathlib import Path
import shutil
import subprocess

import pytest


WATCHER = Path(__file__).resolve().parents[1] / "tmux-agent-watch.sh"

TMUX = """tmux() {
case "$1" in
    has-session) return 0 ;;
    display-message) printf '42 %%7 123 0\\n' ;;
    list-panes)
        if [ "$SCENARIO" = changed ] && [ -f pasted ]; then
            printf '42 %%7 456 0\\n'
        else
            printf '42 %%7 123 0\\n42 %%7 123 0\\n'
        fi ;;
    capture-pane)
        if [ "$SCENARIO" = capture ]; then return 1; fi
        if [ -f entered ]; then printf 'answer\\n'; fi
        if [ -f pasted ] && [ ! -f entered ]; then
            IFS= read -r message < pasted
            printf '❯ %s\\n' "$message"
        elif [ "$SCENARIO" = draft ]; then
            printf '❯ existing draft\\n'
        else
            printf '❯ \\n'
        fi ;;
    send-keys)
        printf '%s\\n' "$*" >> keys
        [ "$3" = %7 ] || [ "$3" = old:0.0 ] || return 99
        if [ "${*: -1}" = Enter ]; then
            [ "$SCENARIO" != enter ] || return 1
            : > entered
        else
            [ "$SCENARIO" != paste ] || return 1
            printf '%s\\n' "${*: -1}" > pasted
        fi ;;
    *) return 99 ;;
esac
}
sleep() { :; }
"""


@pytest.mark.parametrize(
    ("scenario", "status", "sent", "enter_attempted"),
    [
        ("ok", 0, True, True),
        ("paste", 6, False, False),
        ("enter", 6, False, True),
        ("restart", 3, False, False),
        ("late-restart", 3, False, False),
        ("changed", 2, False, False),
        ("draft", 3, False, False),
        ("capture", 2, False, False),
    ],
)
def test_watch_with_stub(tmp_path, scenario, status, sent, enter_attempted):
    bash = shutil.which("bash")
    if not bash:
        pytest.skip("Bash is required to run the tmux watcher stub")
    # Copy to a disposable cwd; neither command can address the operator's tmux server.
    shutil.copyfile(WATCHER, tmp_path / "watch.sh")
    for name, script in {
        "tmux-stub": TMUX,
        "restart-check": (
            "#!/usr/bin/env bash\n"
            '[ "$SCENARIO" != restart ] && '
            '{ [ "$SCENARIO" != late-restart ] || [ ! -f pasted ]; }\n'
        ),
    }.items():
        path = tmp_path / name
        path.write_text(script, encoding="utf-8", newline="\n")
        path.chmod(0o755)
    env = {**os.environ, "SCENARIO": scenario, "LC_ALL": "C.UTF-8"}
    for key in ("BASH_ENV", "ENV", "TMUX", "TMUX_PANE"):
        env.pop(key, None)
    for key in (
        "HOME", "XDG_CONFIG_HOME", "XDG_DATA_HOME", "XDG_STATE_HOME", "XDG_CACHE_HOME",
        "APPDATA", "HERMES_HOME", "CLAUDE_CONFIG_DIR",
    ):
        env[key] = str(tmp_path / key)
    result = subprocess.run(
        [
            bash, "--noprofile", "--norc", "-c",
            'export TARGET=old:0.0 MSG="test instruction" '
            'EXPECTED_PANE_PID=123 RESTART_CHECK="$PWD/restart-check" POLL_S=15; '
            '. ./tmux-stub && [ "$(type -t tmux)" = function ] && . ./watch.sh',
        ],
        cwd=tmp_path,
        env=env,
        capture_output=True,
        timeout=110,
        creationflags=subprocess.CREATE_NO_WINDOW if os.name == "nt" else 0,
    )
    log = (tmp_path / "watch.log").read_text(encoding="utf-8")
    keys_path = tmp_path / "keys"
    keys = keys_path.read_text(encoding="utf-8") if keys_path.exists() else ""
    assert result.returncode == status, (log, keys, result.stderr)
    assert ("SENT:" in log) == sent
    assert (" Enter" in keys) == enter_attempted
    if scenario == "ok":
        assert all("-t %7 " in line for line in keys.splitlines())
