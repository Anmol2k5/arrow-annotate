from arrow.providers import (
    ClaudeProvider,
    CodexProvider,
    ProviderStatus,
    RunRequest,
    SafetyCategory,
    classify_command,
    default_deny,
)


class FakeProcess:
    def __init__(self, lines, returncode=0):
        self._lines = list(lines)
        self.returncode = returncode
        self.stdout = iter(self._lines)
        self._terminated = False
        self._polled = None

    def wait(self):
        return self.returncode

    def poll(self):
        return self._polled

    def terminate(self):
        self._terminated = True
        self._polled = -15


def _which_yes(name):
    return f"/usr/bin/{name}"


def _which_no(name):
    return None


def test_detect_installed():
    p = CodexProvider(which_fn=_which_yes)
    assert p.detect() is True


def test_detect_not_installed_sets_status():
    p = CodexProvider(which_fn=_which_no)
    assert p.detect() is False
    assert p.get_status() == ProviderStatus.NOT_INSTALLED


def test_validate_requires_repo(tmp_path):
    p = CodexProvider(which_fn=_which_yes)
    assert p.validate(str(tmp_path)).ok is True
    bad = p.validate(str(tmp_path / "missing"))
    assert bad.ok is False


def test_validate_requires_install(tmp_path):
    p = CodexProvider(which_fn=_which_no)
    result = p.validate(str(tmp_path))
    assert result.ok is False
    assert "not found" in result.reason


def test_codex_build_command(tmp_path):
    p = CodexProvider(which_fn=_which_yes)
    req = RunRequest(capture_id="c1", repository_path=str(tmp_path), prompt="do it")
    cmd = p.build_command(req)
    assert cmd[0] == "codex"
    assert "do it" in cmd
    assert str(tmp_path) in cmd


def test_claude_build_command_permission_mode(tmp_path):
    p = ClaudeProvider(which_fn=_which_yes, permission_mode="acceptEdits")
    req = RunRequest(capture_id="c1", repository_path=str(tmp_path), prompt="fix bug")
    cmd = p.build_command(req)
    assert cmd[0] == "claude"
    assert "--permission-mode" in cmd
    assert "acceptEdits" in cmd


def test_start_run_uses_no_shell_and_cwd(tmp_path):
    captured = {}

    def fake_popen(command, cwd, **kwargs):
        captured["command"] = command
        captured["cwd"] = cwd
        captured["kwargs"] = kwargs
        return FakeProcess(["line1", "line2"], returncode=0)

    p = CodexProvider(which_fn=_which_yes, popen_fn=fake_popen)
    req = RunRequest(capture_id="c1", repository_path=str(tmp_path), prompt="go")
    p.start_run(req)
    assert captured["cwd"] == str(tmp_path)
    assert isinstance(captured["command"], list)
    assert "shell" not in captured["kwargs"]
    assert p.get_status() == ProviderStatus.RUNNING


def test_stream_events_completed(tmp_path):
    def fake_popen(command, cwd, **kwargs):
        return FakeProcess(["building", "editing"], returncode=0)

    p = CodexProvider(which_fn=_which_yes, popen_fn=fake_popen)
    p.start_run(RunRequest(capture_id="c1", repository_path=str(tmp_path), prompt="go"))
    events = list(p.stream_events())
    types = [e.type for e in events]
    assert "log" in types
    assert events[-1].type == "done"
    assert p.get_status() == ProviderStatus.COMPLETED


def test_stream_events_failure(tmp_path):
    def fake_popen(command, cwd, **kwargs):
        return FakeProcess(["oops"], returncode=2)

    p = CodexProvider(which_fn=_which_yes, popen_fn=fake_popen)
    p.start_run(RunRequest(capture_id="c1", repository_path=str(tmp_path), prompt="go"))
    events = list(p.stream_events())
    assert events[-1].type == "error"
    assert p.get_status() == ProviderStatus.FAILED


def test_cancel_run(tmp_path):
    proc = FakeProcess(["x"], returncode=0)

    def fake_popen(command, cwd, **kwargs):
        return proc

    p = CodexProvider(which_fn=_which_yes, popen_fn=fake_popen)
    p.start_run(RunRequest(capture_id="c1", repository_path=str(tmp_path), prompt="go"))
    p.cancel_run()
    assert proc._terminated is True
    assert p.get_status() == ProviderStatus.CANCELLED


def test_start_run_fails_without_install(tmp_path):
    import pytest
    p = CodexProvider(which_fn=_which_no)
    with pytest.raises(RuntimeError):
        p.start_run(RunRequest(capture_id="c1", repository_path=str(tmp_path), prompt="go"))


def test_classify_command():
    assert classify_command("rm -rf /") == SafetyCategory.DELETE_FILES
    assert classify_command("git push origin main") == SafetyCategory.PUSH
    assert classify_command("git commit -m x") == SafetyCategory.COMMIT
    assert classify_command("pip install requests") == SafetyCategory.INSTALL_PACKAGES
    assert classify_command("ls -la") is None


def test_confirm_command_denies_by_default(tmp_path):
    p = CodexProvider(which_fn=_which_yes)  # default_deny
    assert p.confirm_command("ls") is True  # not sensitive
    assert p.confirm_command("git push") is False  # sensitive, denied


def test_confirm_command_allows_when_confirmed(tmp_path):
    p = CodexProvider(which_fn=_which_yes, confirm=lambda cat, detail: True)
    assert p.confirm_command("git push") is True


def test_default_deny_returns_false():
    assert default_deny(SafetyCategory.PUSH, "git push") is False


def test_codex_command_uses_explicit_sandbox_and_image_attachment(tmp_path):
    image = tmp_path / 'annotated.png'
    image.write_bytes(b'image')
    provider = CodexProvider(which_fn=_which_yes)
    command = provider.build_command(RunRequest(
        capture_id='c', repository_path=str(tmp_path), prompt='--help', assets={'annotated': str(image)}))
    assert command[command.index('--sandbox') + 1] == 'workspace-write'
    assert command[command.index('--image') + 1] == str(image)
    assert command[-2:] == ['--', '--help']


def test_claude_prompt_cannot_be_interpreted_as_cli_option(tmp_path):
    command = ClaudeProvider(which_fn=_which_yes).build_command(RunRequest(
        capture_id='c', repository_path=str(tmp_path), prompt='--dangerously-skip-permissions'))
    assert command[-2:] == ['--', '--dangerously-skip-permissions']


def test_provider_cannot_replace_a_running_process(tmp_path):
    import pytest
    process = FakeProcess([])
    provider = CodexProvider(which_fn=_which_yes, popen_fn=lambda *a, **k: process)
    request = RunRequest(capture_id='c', repository_path=str(tmp_path), prompt='fix')
    provider.start_run(request)
    with pytest.raises(RuntimeError, match='already running'):
        provider.start_run(request)
    assert provider.get_status() == ProviderStatus.RUNNING
