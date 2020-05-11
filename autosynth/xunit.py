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

from autosynth.log import LogCollector
import jinja2

TEMPLATE_FILE = "report.xml.j2"


def write_xml_log(name: str, log_collector: LogCollector, output_file_path: str):
    with open(TEMPLATE_FILE) as fh:
        template = jinja2.Template(fh.read())

    output = template.render(
        name=name,
        failures=len([log for log in log_collector.log_entries if not log.success]),
        log_entries=log_collector.log_entries,
    )

    with open(output_file_path, "w") as fh:
        fh.write(output)
