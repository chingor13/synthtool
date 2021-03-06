# Copyright 2018 Google LLC
#
# Licensed under the Apache License, Version 2.0 (the "License");
# you may not use this file except in compliance with the License.
# You may obtain a copy of the License at
#
#     https://www.apache.org/licenses/LICENSE-2.0
#
# Unless required by applicable law or agreed to in writing, software
# distributed under the License is distributed on an "AS IS" BASIS,
# WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
# See the License for the specific language governing permissions and
# limitations under the License.

import json

from synthtool import metadata


def test_add_git_source():
    metadata.reset()

    metadata.add_git_source(sha="sha", name="name", remote="remote")

    current = metadata.get()

    assert current.sources[0].git.sha == "sha"
    assert current.sources[0].git.name == "name"
    assert current.sources[0].git.remote == "remote"


def test_add_generator_source():
    metadata.reset()

    metadata.add_generator_source(name="name", version="1.2.3")

    current = metadata.get()

    assert current.sources[0].generator.name == "name"
    assert current.sources[0].generator.version == "1.2.3"


def test_add_template_source():
    metadata.reset()

    metadata.add_template_source(name="name", version="1.2.3")

    current = metadata.get()

    assert current.sources[0].template.name == "name"
    assert current.sources[0].template.version == "1.2.3"


def test_add_client_destination():
    metadata.reset()

    metadata.add_client_destination(
        source="source",
        api_name="api",
        api_version="v1",
        language="py",
        generator="gen",
        config="config",
    )

    current = metadata.get()

    assert current.destinations[0].client.source == "source"
    assert current.destinations[0].client.api_name == "api"
    assert current.destinations[0].client.api_version == "v1"
    assert current.destinations[0].client.language == "py"
    assert current.destinations[0].client.generator == "gen"
    assert current.destinations[0].client.config == "config"


def test_write(tmpdir):
    metadata.reset()

    metadata.add_git_source(sha="sha", name="name", remote="remote")

    output_file = tmpdir / "synth.metadata"

    metadata.write(str(output_file))

    raw = output_file.read()

    # Ensure the file was written, that *some* metadata is in it, and that it
    # is valid JSON.
    assert raw
    assert "sha" in raw
    data = json.loads(raw)
    assert data
    assert data["updateTime"] is not None
