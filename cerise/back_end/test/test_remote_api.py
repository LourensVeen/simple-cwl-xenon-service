from .mock_store import MockStore
from cerise.test.fixture_jobs import WcJob
from cerise.back_end.remote_api import RemoteApi

from cerise.back_end.test.conftest import MockConfig

import cerulean

import os
import pytest


def test_install(tmpdir):
    config = MockConfig(str(tmpdir))
    remote_api_files = RemoteApi(config)

    local_api_dir = os.path.join(os.path.dirname(__file__), 'api')
    remote_api_files.install(local_api_dir)

    # check that steps were staged
    assert (tmpdir / 'api' / 'test' / 'steps' / 'test' / 'wc.cwl').isfile()

    # check that install script was run
    assert (tmpdir / 'api' / 'test' / 'files' / 'test' /
            'test_file.txt').isfile()
