"""Offline fixtures exercise workflow selection and complete-acceptance failure paths."""

import json
import os
import shutil
import subprocess
from pathlib import Path

import pytest
import yaml

ROOT = Path(__file__).resolve().parents[2]


@pytest.fixture
def workflow():
    return yaml.safe_load((ROOT / '.github/workflows/v1.yml').read_text())


def test_lanes_are_independent_and_offline_has_only_its_prerequisites(workflow):
    offline, live = (workflow['jobs'][name] for name in ('v1-offline', 'v1-local'))
    assert 'needs' not in offline and 'needs' not in live
    commands = '\n'.join(step.get('run', '') for step in offline['steps'])
    assert 'uv sync --locked --extra dev\n' in commands
    assert '--extra legacy' not in commands
    assert 'cfn-lint==1.57.2' in commands
    assert '--python .cache/v1-cfn-lint/bin/python' in commands
    assert 'echo "$PWD/.cache/v1-cfn-lint/bin" >> "$GITHUB_PATH"' in commands
    assert 'make lint-cfn CFN_LINT_ARGS=--require' in commands
    assert 'make test-aws-v1' in commands and 'make test-v1' in commands
    assert '-k skeleton' in commands and '--require-integration' in commands
    assert 'command -v aws' in commands
    for expensive in ('playwright', 'ffmpeg', 'moto[server]', 'v1-up', 'verify-v1', 'coverage'):
        assert expensive not in commands
    assert 'V1_COVERAGE' not in offline.get('env', {})
    assert live['env']['V1_COVERAGE'] == '1' and live['env']['V1_BROWSER'] == '1'
    assert all('continue-on-error' not in lane for lane in (offline, live))
    assert all('continue-on-error' not in step
               for lane in (offline, live) for step in lane['steps'])
    for target in ('test-aws-v1', 'test-v1'):
        recipe = (ROOT / 'Makefile').read_text().split(f'\n{target}:', 1)[1].split('\n\n')[0]
        assert '--offline-fast' in recipe and '--cov' not in recipe and 'unmeasured' not in recipe


def evaluate(condition, cancelled=False, **values):
    """Evaluate just the boolean expression grammar used by these workflow conditions."""
    expression = condition.removeprefix('${{').removesuffix('}}').strip()
    expression = expression.replace('!cancelled()', repr(not cancelled))
    expression = expression.replace('!inputs.images', 'not inputs.images')
    for key, value in sorted(values.items(), key=lambda pair: -len(pair[0])):
        expression = expression.replace(key, repr(value))
    expression = expression.replace('&&', ' and ').replace('||', ' or ')
    assert all(token not in expression for token in ('inputs.', 'github.', 'needs.'))
    return eval(expression, {'__builtins__': {}})


def test_call_defaults_and_manual_dispatch_are_complete(workflow):
    trigger = workflow[True]
    inputs = trigger['workflow_call']['inputs']
    assert {name: inputs[name]['default'] for name in (
        'run_offline', 'run_live', 'images', 'auto_images', 'flow'
    )} == {'run_offline': True, 'run_live': True, 'images': False,
          'auto_images': True, 'flow': 'all'}
    assert trigger['workflow_dispatch']['inputs']['flow']['default'] == 'all'
    assert trigger['workflow_dispatch']['inputs']['images']['default'] is False
    assert 'auto_images' not in trigger['workflow_dispatch']['inputs']
    for lane, switch in (('v1-offline', 'run_offline'), ('v1-local', 'run_live')):
        assert trigger['workflow_dispatch']['inputs'][switch]['default'] is True
        condition = workflow['jobs'][lane]['if']
        for event in ('pull_request', 'push', 'workflow_dispatch'):
            for enabled in (True, False):
                assert evaluate(condition, **{'github.event_name': event,
                                              f'inputs.{switch}': enabled}) == enabled


@pytest.mark.parametrize('event', ['pull_request', 'push', 'workflow_dispatch'])
@pytest.mark.parametrize('images', [False, True])
@pytest.mark.parametrize('auto', [False, True])
@pytest.mark.parametrize('path_result,changed', [('success', 'true'), ('success', 'false'),
                                               ('skipped', ''), ('failure', '')])
def test_images_explicit_override_auto_disable_and_unavailable_classifier(
    workflow, event, images, auto, path_result, changed
):
    condition = workflow['jobs']['images']['if']
    selected = evaluate(condition, **{
        'github.event_name': event, 'inputs.images': images, 'inputs.auto_images': auto,
        'needs.image-paths.result': path_result, 'needs.image-paths.outputs.changed': changed,
    })
    assert selected == (images or (auto and (path_result != 'success' or changed == 'true')))
    classify = evaluate(workflow['jobs']['image-paths']['if'], **{
        'github.event_name': event, 'inputs.images': images, 'inputs.auto_images': auto,
    })
    assert classify == (auto and not images)


def git(root, *args):
    return subprocess.run(['git', '-C', str(root), *args], check=True,
                          capture_output=True, text=True).stdout.strip()


@pytest.fixture
def repository(tmp_path):
    root = tmp_path / 'source'
    root.mkdir()
    git(root, 'init', '-q')
    git(root, '-c', 'user.name=CI fixture', '-c', 'user.email=ci@example.test',
        'commit', '-q', '--allow-empty', '-m', 'base')
    return root, git(root, 'rev-parse', 'HEAD')


def classify(workflow, tmp_path, repository, *, event='pull_request', base=None, fail_diff=False):
    root, original_base = repository
    step = next(s for s in workflow['jobs']['image-paths']['steps'] if s.get('id') == 'diff')
    output = tmp_path / 'output'
    output.write_text('')
    env = {**os.environ, 'EVENT': event, 'PR_BASE': original_base if base is None else base,
           'PUSH_BEFORE': original_base if base is None else base,
           'PYTHONPATH': str(ROOT), 'GITHUB_OUTPUT': str(output),
           'GITHUB_STEP_SUMMARY': str(tmp_path / 'summary')}
    if fail_diff:
        tool = tmp_path / 'tools'
        tool.mkdir()
        wrapper = tool / 'git'
        wrapper.write_text('#!/bin/bash\nif [ "$1" = diff ]; then exit 2; fi\n'
                           f'exec {shutil.which("git")} "$@"\n')
        wrapper.chmod(0o755)
        env['PATH'] = str(tool) + os.pathsep + env['PATH']
    subprocess.run(['bash', '-c', step['run']], cwd=root, env=env, check=True,
                   capture_output=True, text=True, timeout=10)
    return output.read_text().strip()


@pytest.mark.parametrize('path,expected', [
    ('media/db/models.py', True), ('processing/migrations/0001.py', True),
    ('media_engine/ffmpeg.py', True), ('contracts/media.json', True), ('delivery/aws.py', True),
    ('runtime_support/env.py', True), ('deploy/v1/media.Dockerfile', True),
    ('deploy/aws/v1/template.json', True), ('scripts/aws/v1/bootstrap.py', True),
    ('uv.lock', True), ('pyproject.toml', True), ('.dockerignore', True),
    ('.github/workflows/v1.yml', True), ('Makefile', True),
    ('docs/project2-worklog.txt', False), ('frontend/src/App.tsx', False),
])
def test_actual_build_inputs_select_images(workflow, repository, tmp_path, path, expected):
    root, _ = repository
    target = root / path
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text('changed')
    git(root, 'add', '.')
    git(root, '-c', 'user.name=CI fixture', '-c', 'user.email=ci@example.test',
        'commit', '-qm', 'change')
    assert classify(workflow, tmp_path, repository) == f'changed={str(expected).lower()}'


@pytest.mark.parametrize('base,event,fail_diff', [
    ('', 'pull_request', False), ('0' * 40, 'push', False),
    ('f' * 40, 'push', False), ('', 'unknown', False), (None, 'pull_request', True),
])
def test_unavailable_image_diff_selects_conservatively(
    workflow, repository, tmp_path, base, event, fail_diff
):
    assert classify(workflow, tmp_path, repository, base=base, event=event,
                    fail_diff=fail_diff) == 'changed=true'


def test_empty_known_diff_skips_images(workflow, repository, tmp_path):
    assert classify(workflow, tmp_path, repository) == 'changed=false'


def test_rename_out_of_image_tree_still_builds(workflow, repository, tmp_path):
    root, _ = repository
    (root / 'media').mkdir()
    (root / 'media/models.py').write_text('source')
    git(root, 'add', '.')
    git(root, '-c', 'user.name=CI fixture', '-c', 'user.email=ci@example.test',
        'commit', '-qm', 'old source')
    base = git(root, 'rev-parse', 'HEAD')
    (root / 'docs').mkdir()
    git(root, 'mv', 'media/models.py', 'docs/models.py')
    git(root, '-c', 'user.name=CI fixture', '-c', 'user.email=ci@example.test',
        'commit', '-qm', 'move source')
    assert classify(workflow, tmp_path, repository, base=base) == 'changed=true'


def test_pr_diff_ignores_base_only_changes_after_common_ancestor(workflow, repository, tmp_path):
    root, original = repository
    git(root, 'checkout', '-qb', 'target')
    (root / 'media').mkdir()
    (root / 'media/models.py').write_text('base-only source')
    git(root, 'add', '.')
    git(root, '-c', 'user.name=CI fixture', '-c', 'user.email=ci@example.test',
        'commit', '-qm', 'target advances')
    base = git(root, 'rev-parse', 'HEAD')
    git(root, 'checkout', '-qb', 'candidate', original)
    (root / 'docs').mkdir()
    (root / 'docs/readme.md').write_text('candidate docs')
    git(root, 'add', '.')
    git(root, '-c', 'user.name=CI fixture', '-c', 'user.email=ci@example.test',
        'commit', '-qm', 'candidate change')
    assert classify(workflow, tmp_path, repository, base=base) == 'changed=false'


@pytest.mark.parametrize('status,complete,cloud', [
    ('PASS', 'PASS', 'NOT_RUN'), ('FAIL', 'PASS', 'NOT_RUN'),
    ('PASS', 'NOT_RUN', 'NOT_RUN'), ('PASS', 'PASS', 'PASS'),
])
def test_complete_acceptance_assertions_are_executable(workflow, tmp_path, monkeypatch,
                                                      status, complete, cloud):
    steps = workflow['jobs']['v1-local']['steps']
    command = next(s['run'] for s in steps if s.get('name', '').startswith('Require complete'))
    validation = command.split("<<'PY'\n", 1)[1].rsplit('\nPY', 1)[0]
    folder = tmp_path / '.cache/v1-runtime/test/evidence-test'
    folder.mkdir(parents=True)
    (folder / 'manifest.json').write_text(json.dumps({
        'status': status, 'complete_v1_acceptance': complete, 'cloud_acceptance': cloud,
    }))
    monkeypatch.chdir(tmp_path)
    monkeypatch.setenv('V1_RUN_ID', 'test')
    if (status, complete, cloud) == ('PASS', 'PASS', 'NOT_RUN'):
        exec(compile(validation, 'acceptance', 'exec'), {})
    else:
        with pytest.raises(AssertionError):
            exec(compile(validation, 'acceptance', 'exec'), {})


def test_live_keeps_source_coverage_and_owned_cleanup(workflow):
    steps = workflow['jobs']['v1-local']['steps']
    upload = next(s for s in steps if s.get('with', {}).get('name') == 'v1-coverage-data')
    assert upload['with']['path'] == 'artifacts/coverage/.coverage.v1-integration*'
    assert upload['with']['if-no-files-found'] == 'error'
    assert upload['with']['include-hidden-files']
    cleanup = next(s for s in steps if s.get('name', '').startswith('Stop only'))
    assert cleanup['if'] == 'always()'
    assert '$V1_RUN_ID/runtime.json' in cleanup['run'] and 'make v1-down' in cleanup['run']


def test_expensive_images_honor_workflow_cancellation(workflow):
    assert not evaluate(workflow['jobs']['images']['if'], cancelled=True, **{
        'github.event_name': 'pull_request', 'inputs.images': True, 'inputs.auto_images': False,
        'needs.image-paths.result': 'skipped', 'needs.image-paths.outputs.changed': '',
    })
