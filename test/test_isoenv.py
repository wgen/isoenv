

# This file is part of isoenv
#
# Copyright (c) 2012 Wireless Generation, Inc.
#
# Permission is hereby granted, free of charge, to any person obtaining a copy
# of this software and associated documentation files (the "Software"), to deal
# in the Software without restriction, including without limitation the rights
# to use, copy, modify, merge, publish, distribute, sublicense, and/or sell
# copies of the Software, and to permit persons to whom the Software is
# furnished to do so, subject to the following conditions:
#
# The above copyright notice and this permission notice shall be included in
# all copies or substantial portions of the Software.
#
# THE SOFTWARE IS PROVIDED "AS IS", WITHOUT WARRANTY OF ANY KIND, EXPRESS OR
# IMPLIED, INCLUDING BUT NOT LIMITED TO THE WARRANTIES OF MERCHANTABILITY,
# FITNESS FOR A PARTICULAR PURPOSE AND NONINFRINGEMENT. IN NO EVENT SHALL THE
# AUTHORS OR COPYRIGHT HOLDERS BE LIABLE FOR ANY CLAIM, DAMAGES OR OTHER
# LIABILITY, WHETHER IN AN ACTION OF CONTRACT, TORT OR OTHERWISE, ARISING FROM,
# OUT OF OR IN CONNECTION WITH THE SOFTWARE OR THE USE OR OTHER DEALINGS IN
# THE SOFTWARE.

from decorator import decorator
import os.path
from contextlib import contextmanager
from tempfile import mkdtemp
from shutil import rmtree
from os import mkdir
from itertools import combinations
import json

from mock import patch
from nose.tools import assert_equals

from isoenv import compile_directories, map_files


def fake_isdir(paths):
    paths = [os.path.realpath(path) for path in paths]

    def isdir(path):
        print(path, paths)
        return os.path.realpath(path) in paths
    return isdir


def isdict(thing):
    return hasattr(thing, 'items')


def fake_map_directory(file_structure):
    def flatten(src_dir):
        for name, contents in list(src_dir.items()):
            if isdict(contents):
                for path, file_contents in flatten(contents):
                    yield os.path.join(name, path), file_contents
            else:
                yield name, contents

    def map_directory(src, dest):
        root_dir = file_structure
        for seg in src.split('/'):
            root_dir = root_dir[seg]
        return dict((path.replace(src, dest), src)
                    for path, contents in flatten(root_dir))


def mock_filesystem(fs_dict):
    def contents(path, fs=fs_dict):
        segs = list(filter(None, path.split('/')))
        return contents('/'.join(segs[1:]), fs[segs[0]]) if len(segs) > 1 else fs[segs[0]]

    def isdir(path):
        return isdict(contents(path))

    def walk(top):
        def _walk(fs, path):
            if isdict(fs):
                dirs = sorted(
                    name
                    for (name, contents)
                    in list(fs.items())
                    if isdict(contents))

                files = sorted(
                    name
                    for (name, contents)
                    in list(fs.items())
                    if not isdict(contents))

                yield (path, dirs, files)
                for dirname in dirs:
                    for (p, d, f) in _walk(fs[dirname], os.path.join(path, dirname)):
                        yield (p, d, f)
        try:
            for (p, d, f) in _walk(contents(top), top):
                yield (p, d, f)
        except KeyError:
            pass

    @decorator
    def dec(func, *args, **kwargs):
        @patch('isoenv.walk', walk)
        def wrapper():
            return func(*args, **kwargs)
        return wrapper()

    return dec


def paths_to_fs_dict(paths):
    fs = {}
    for (path, content) in list(paths.items()):
        segs = path.split('/')
        cur_dir = fs
        for seg in segs[:-1]:
            cur_dir = cur_dir.setdefault(seg, {})
        if content is not None:
            cur_dir[segs[-1]] = content
        else:
            cur_dir.setdefault(segs[-1], {})

    return fs


@contextmanager
def setup_temp_dir(fs_dict):
    def write(base_dir, fs_dict):
        for name, contents in list(fs_dict.items()):
            file_path = os.path.join(base_dir, name)
            if isdict(contents):
                mkdir(file_path)
                write(file_path, contents)
            else:
                with open(file_path, 'w') as out:
                    out.write(contents)

    basedir = mkdtemp()
    try:
        write(basedir, fs_dict)
        yield basedir
    finally:
        rmtree(basedir)


@mock_filesystem(paths_to_fs_dict({
    'repo/public/Properties/ENVIRONMENT_SPECIFIC/env/prop_env_spec_pub': 'prop_env_spec_pub_contents'
}))
def test_repo_with_slash():
    repo = "repo/public/"
    dest = "dest"
    env = "env"
    file_map = map_files([repo], dest, env)
    assert_equals(
        {
            'dest/Properties/prop_env_spec_pub': 'repo/public/Properties/ENVIRONMENT_SPECIFIC/env/prop_env_spec_pub',
        },
        file_map
    )


@mock_filesystem(paths_to_fs_dict({
    'repo/public/Properties/ENVIRONMENT_SPECIFIC/aenv/prop_env_spec_pub': 'prop_aenv_spec_pub',
    'repo/public/Properties/ENVIRONMENT_SPECIFIC/env/prop_env_spec_pub': 'prop_env_spec_pub',
    'repo/public/Properties/ENVIRONMENT_SPECIFIC/zenv/prop_env_spec_pub': 'prop_zenv_spec_pub',
}))
def test_prepare_wrong_env():
    repo = "repo/public"
    dest = "dest"
    env = "env"
    file_map = map_files([repo], dest, env)
    assert_equals(
        {
            'dest/Properties/prop_env_spec_pub': 'repo/public/Properties/ENVIRONMENT_SPECIFIC/env/prop_env_spec_pub',
        },
        file_map
    )


def test_overrides_in_env_spec_plugins():
    for (overridden, overriding) in combinations([
        'repo/public/Properties/file',
        'repo/public/Properties/ENVIRONMENT_SPECIFIC/env/file',
        'repo/ops_private/Properties/file',
        'repo/ops_private/Properties/ENVIRONMENT_SPECIFIC/env/file'
    ], 2):
        yield (check_override, overridden, overriding)


def test_overrides_in_common_files():
    for (overridden, overriding) in combinations([
        'repo/public/Bundler/file',
        'repo/ops_private/Bundler/file',
    ], 2):
        yield (check_override, overridden, overriding)


def check_override(src_path, overriding_path,
                   sources=None, dest='dest', env='env'):
    sources = sources or ['repo/public', 'repo/ops_private']
    fs = paths_to_fs_dict({src_path: 'overridden', overriding_path: 'overriding'})
    print(fs)

    @mock_filesystem(fs)
    def get_file_map():
        return map_files(sources, dest, env)

    file_map = get_file_map()
    print(file_map)

    assert_equals([overriding_path], list(file_map.values()))


def test_compile_writes_file_manifest():
    file_dict = paths_to_fs_dict({
        'repo/public/Properties/dir/prop_env_spec_pub': 'prop_env_spec_pub_overridden',
        'repo/public/Properties/dir/prop_env_spec_priv': 'prop_env_spec_priv_overridden',
        'repo/public/Properties/ENVIRONMENT_SPECIFIC/env/dir/prop_env_spec_pub': 'prop_env_spec_pub_contents',
        'repo/public/Properties/ENVIRONMENT_SPECIFIC/env/dir/prop_env_spec_priv': 'prop_env_spec_priv_overridden',
        'repo/ops_private/Properties/ENVIRONMENT_SPECIFIC/env/dir/prop_env_spec_priv': 'prop_env_spec_priv_contents',
        'repo/public/dir/common_pub': 'common_pub_contents',
        'repo/ops_private/dir/common_priv': 'common_priv_overridden',
    })

    with setup_temp_dir(file_dict) as basedir:
        sources = [
            os.path.join(basedir, 'repo', 'public'),
            os.path.join(basedir, 'repo', 'ops_private')
        ]
        compile_directories(sources, os.path.join(basedir, 'dest'), 'env', False)

        with open(os.path.join(basedir, 'dest', 'etc', 'mapped_files.json'), 'r') as manifest_file:
            manifest = json.load(manifest_file)
            assert_equals(
                {
                    os.path.join(basedir, 'dest/Properties/dir/prop_env_spec_pub'): os.path.join(basedir, 'repo/public/Properties/ENVIRONMENT_SPECIFIC/env/dir/prop_env_spec_pub'),
                    os.path.join(basedir, 'dest/Properties/dir/prop_env_spec_priv'): os.path.join(basedir, 'repo/ops_private/Properties/ENVIRONMENT_SPECIFIC/env/dir/prop_env_spec_priv'),
                    os.path.join(basedir, 'dest/dir/common_priv'): os.path.join(basedir, 'repo/ops_private/dir/common_priv'),
                    os.path.join(basedir, 'dest/dir/common_pub'): os.path.join(basedir, 'repo/public/dir/common_pub'),
                },
                manifest
            )


def test_compile_deletes_non_git():
    file_dict = paths_to_fs_dict({
        'repo/public/Properties/dir/prop_env_spec_pub': 'prop_env_spec_pub_overridden',
        'repo/public/Properties/dir/prop_env_spec_priv': 'prop_env_spec_priv_overridden',
        'repo/public/Properties/ENVIRONMENT_SPECIFIC/env/dir/prop_env_spec_pub': 'prop_env_spec_pub_contents',
        'repo/public/Properties/ENVIRONMENT_SPECIFIC/env/dir/prop_env_spec_priv': 'prop_env_spec_priv_overridden',
        'repo/ops_private/Properties/ENVIRONMENT_SPECIFIC/env/dir/prop_env_spec_priv': 'prop_env_spec_priv_contents',
        'repo/public/dir/common_pub': 'common_pub_contents',
        'repo/public/dir/common_priv': 'common_priv_overridden',
        'repo/ops_private/dir/common_priv': 'common_priv_contents',
        'dest/.git/git_contents': 'git_contents',
        'etc/subdir/not_git_contents': 'not_git_contents',
    })

    with setup_temp_dir(file_dict) as basedir:
        sources = [
            os.path.join(basedir, 'repo', 'public'),
            os.path.join(basedir, 'repo', 'ops_private')
        ]
        compile_directories(sources, os.path.join(basedir, 'dest'), 'env', False)
        assert os.path.exists(os.path.join(basedir, 'dest', '.git', 'git_contents'))
        assert not os.path.exists(os.path.join(basedir, 'dest', 'etc', 'subdir', 'not_git_contents'))


def test_etc_shadow():
    contents = {
        'bcfg2/ops_private/Cfg/ENVIRONMENT_SPECIFIC/staging/etc/shadow/shadow': 'staging',
        'bcfg2/ops_private/Cfg/ENVIRONMENT_SPECIFIC/production/etc/shadow/shadow': 'production',
        'bcfg2/ops_private/Cfg/etc/shadow/shadow': 'dev'
    }
    file_dict = paths_to_fs_dict(contents)

    @mock_filesystem(file_dict)
    def get_file_map(env):
        return map_files(['bcfg2/ops_private'], '', env)

    for env in ['staging', 'production', 'dev']:
        file_map = get_file_map(env)
        print(file_map)
        assert_equals(env, contents[file_map['Cfg/etc/shadow/shadow']])
