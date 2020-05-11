# Copyright 2020 Google LLC
#
# Licensed under the Apache License, Version 2.0 (the "License");
# you may not use this file except in compliance with the License.
# You may obtain a copy of the License at
#
#     http://www.apache.org/licenses/LICENSE-2.0
#
# Unless required by applicable law or agreed to in writing, software
# distributed under the License is distributed on an "AS IS" BASIS,
# WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
# See the License for the specific language governing permissions and
# limitations under the License.

from synthtool.log import configure_logger


logger = configure_logger("autosynth")


class LogCollector:
    def __init__(self):
        self.successes = []
        self.failures = []

    def add_success(self, name: str, log: str):
        self.successes.append((name, log))

    def add_failure(self, name: str, log: str):
        self.failures.append((name, log))
