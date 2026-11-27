"""Bound the run store without pruning live, recent, or ledger-referenced runs."""

import math
import os
import shutil
import stat
import subprocess
import time
import uuid
import warnings
from contextlib import ExitStack, suppress
from datetime import datetime, timezone
from pathlib import Path

import gdd_process
import skill_config
from run_process import DATE_RE, read_state, sanitize, start_lock_slug
from run_supervisors import WINDOWS_DETACH

LEDGER_COLUMNS = (
    "ts", "repo", "goal", "stage", "base_sha", "head_sha", "pr", "gates",
    "rounds_simplify", "rounds_review", "findings", "next_action", "note",
)


def gc_setting(key, default):
    value = skill_config.resolve("gdd", key, default=default)
    if key == "GDD_RUN_MAX_MB" and str(value).strip().lower() == "off":
        return 0
    value = float(value)
    if not math.isfinite(value) or (key != "GDD_RUN_MAX_MB" and value < 0):
        raise ValueError(f"invalid {key}: {value}")
    return value


def gc_due(stamp, interval):
    try:
        return not interval or time.time() - stamp.lstat().st_mtime >= interval
    except FileNotFoundError:
        return True


def gc_stat(info, kind):
    return kind(info.st_mode) and not getattr(info, "st_file_attributes", 0) & stat.FILE_ATTRIBUTE_REPARSE_POINT


def gc_regular_path(path):
    with suppress(FileNotFoundError):
        if not gc_stat(path.lstat(), stat.S_ISREG):
            raise OSError(f"not a regular file: {path}")
    return path


def gc_entries(folder):
    try:
        if not gc_stat(folder.lstat(), stat.S_ISDIR):
            return
        with os.scandir(folder) as entries:
            for entry in entries:
                with suppress(FileNotFoundError):
                    yield Path(entry.path), entry.stat(follow_symlinks=False)
    except FileNotFoundError:
        pass


def gc_size(run):
    total, pending = 0, [run]
    while pending:
        for path, info in gc_entries(pending.pop()):
            if gc_stat(info, stat.S_ISDIR):
                pending.append(path)
            elif gc_stat(info, stat.S_ISREG):
                total += info.st_size
    return total


def gc_claiming(root, slug):
    try:
        if slug not in gc_regular_path(root / ".gc.claim").read_text(encoding="utf-8").splitlines():
            return False
        with gc_regular_path(root / ".gc.lock").open("r+b") as handle:
            return not gdd_process.try_file_lock(handle)
    except (OSError, ValueError):
        return False


def gc_ledger_names(is_windows):
    home = os.environ.get("XDG_STATE_HOME") or os.path.join(os.path.expanduser("~"), ".local", "state")
    ledger = skill_config.resolve("gdd", "GDD_STATE_FILE", default=os.path.join(home, "gdd", "ledger.tsv"))
    names = set()
    try:
        with Path(ledger).expanduser().open(encoding="utf-8-sig") as handle:
            note = LEDGER_COLUMNS.index("note")
            first = True
            for raw in handle:
                line = raw.rstrip("\r\n")
                if not line:
                    continue
                cells = line.split("\t")
                if first:
                    first = False
                    if "note" in cells:
                        note = cells.index("note")
                        continue
                    if "stage" in cells and "goal" in cells:
                        return None
                if len(cells) > note and (value := cells[note].strip()).startswith("run="):
                    names.add(start_lock_slug(value[4:], is_windows))
    except FileNotFoundError:
        pass
    return names


class RunGC:
    """Schedule and collect using the entry point's process and interpreter bindings."""

    def __init__(self, runtime, runner_script):
        self.runtime = runtime
        self.runner_script = runner_script

    def spawn_auto_gc(self, root):
        root = Path(root)
        with suppress(OSError, ValueError):
            if (gc_setting("GDD_RUN_MAX_MB", 512) <= 0 or
                    not gc_due(root / ".gc.stamp", gc_setting("GDD_RUN_GC_MIN_INTERVAL_SECONDS", 60))):
                return
            with gc_regular_path(root / ".gc.lock").open("a+b") as handle:
                if not gdd_process.try_file_lock(handle):
                    return
            argv = [self.runtime.runner_interpreter(), "-B", self.runner_script, "_gc", "--run-root", str(root)]
            with warnings.catch_warnings():
                warnings.simplefilter("ignore", ResourceWarning)
                if self.runtime.IS_WINDOWS:
                    for flags in (WINDOWS_DETACH | gdd_process.BREAKAWAY, WINDOWS_DETACH):
                        try:
                            gdd_process.popen(argv, stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL,
                                              stderr=subprocess.DEVNULL, creationflags=flags)
                            break
                        except OSError as exc:
                            if flags == WINDOWS_DETACH or getattr(exc, "winerror", None) != 5:
                                raise
                else:
                    gdd_process.popen(argv, stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL,
                                      stderr=subprocess.DEVNULL, start_new_session=True)

    def gc_runs(self, run_root, now=None):
        with suppress(OSError, ValueError):
            budget = gc_setting("GDD_RUN_MAX_MB", 512) * 1024**2
            if budget > 0:
                root = Path(run_root).resolve()
                stamp = gc_regular_path(root / ".gc.stamp")
                with gc_regular_path(root / ".gc.lock").open("a+b") as handle:
                    if gdd_process.try_file_lock(handle) and gc_due(
                            stamp, gc_setting("GDD_RUN_GC_MIN_INTERVAL_SECONDS", 60)):
                        now = time.time() if now is None else now
                        if math.isfinite(now):
                            self._prune(root, budget, now - gc_setting("GDD_RUN_RETENTION_DAYS", 7) * 86400)
                            stamp.touch()
        return 0

    def _settled_at(self, run, cutoff):
        marker = (run / "finalized").lstat()
        if not gc_stat(marker, stat.S_ISREG) or marker.st_mtime >= cutoff:
            return None
        if not gc_stat((run / "state.json").lstat(), stat.S_ISREG):
            return None
        state = read_state(run)
        if not state or state.get("state") in ("running", "unknown") or self.runtime.run_alive(run, state):
            return None
        settled = marker.st_mtime
        recorded = False
        for key in ("ended", "started"):
            try:
                timestamp = datetime.fromisoformat(state[key])
                if timestamp.tzinfo is None:
                    timestamp = timestamp.replace(tzinfo=timezone.utc)
                settled = max(settled, timestamp.timestamp())
                recorded = True
                break
            except (KeyError, TypeError, ValueError, OverflowError, OSError):
                continue
        return settled if recorded and settled < cutoff else None

    def _retire(self, root, run, info, slugs, cutoff):
        claim = gc_regular_path(root / ".gc.claim")
        temp_claim = gc_regular_path(root / f".gc.claim.{os.getpid()}.tmp")
        temp_claim.write_text("\n".join(slugs), encoding="utf-8", newline="\n")
        os.replace(temp_claim, claim)
        try:
            with ExitStack() as locks:
                for slug in slugs:
                    path = gc_regular_path(root / f"{slug}.start.lock")
                    handle = locks.enter_context(path.open("a+b"))
                    if not gdd_process.try_file_lock(handle):
                        return None
                current = run.lstat()
                if (not gc_stat(run.parent.lstat(), stat.S_ISDIR) or not gc_stat(current, stat.S_ISDIR)
                        or not os.path.samestat(info, current) or self._settled_at(run, cutoff) is None):
                    return None
                refresh = run / "refresh"
                try:
                    existing = refresh.lstat()
                except FileNotFoundError:
                    existing = None
                if existing is not None and not gc_stat(existing, stat.S_ISREG):
                    return None
                retired = run.with_name(f"~gc-{uuid.uuid4().hex}")
                with refresh.open("a+b") as handle:
                    if not gdd_process.try_file_lock(handle) or self._settled_at(run, cutoff) is None:
                        return None
                    if not self.runtime.IS_WINDOWS:
                        run.rename(retired)
                if self.runtime.IS_WINDOWS:
                    # Windows rejects the rename while a CRT refresh handle is open, including a new claimant.
                    run.rename(retired)
                return retired
        finally:
            with suppress(OSError):
                temp_claim.unlink(missing_ok=True)
                claim.unlink(missing_ok=True)

    def _prune(self, root, budget, cutoff):
        total, runs = 0, []
        for date, info in gc_entries(root):
            if not DATE_RE.fullmatch(date.name) or not gc_stat(info, stat.S_ISDIR):
                continue
            for run, info in gc_entries(date):
                if gc_stat(info, stat.S_ISDIR):
                    if run.name.startswith("~gc-"):
                        with suppress(OSError):
                            shutil.rmtree(run)
                            if date.name != datetime.now().strftime("%Y-%m-%d"):
                                date.rmdir()
                        continue
                    with suppress(FileNotFoundError):
                        info = run.lstat()
                        if gc_stat(info, stat.S_ISDIR):
                            size = gc_size(run)
                            total += size
                            runs.append((run, info, size))
        if total <= budget:
            return
        protected = gc_ledger_names(self.runtime.IS_WINDOWS)
        if protected is None:
            return
        candidates = []
        for run, info, size in runs:
            slugs = (run.name.rsplit(".prev-", 1)[0], run.name)
            slugs = tuple(dict.fromkeys(start_lock_slug(slug, self.runtime.IS_WINDOWS)
                                        for slug in slugs if slug and slug == sanitize(slug)))
            if not slugs or protected.intersection(slugs):
                continue
            with suppress(OSError):
                if (settled := self._settled_at(run, cutoff)) is not None:
                    candidates.append((settled, run, info, slugs, size))
        for _, run, info, slugs, size in sorted(candidates):
            with suppress(OSError):
                if retired := self._retire(root, run, info, slugs, cutoff):
                    shutil.rmtree(retired)
                    total -= size
                    if run.parent.name != datetime.now().strftime("%Y-%m-%d"):
                        with suppress(OSError):
                            run.parent.rmdir()
                    if total <= budget:
                        break
