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

import glob
import os
import xml.etree.ElementTree as ET
import requests
import synthtool as s
import synthtool.gcp as gcp
from synthtool import cache, shell
from synthtool.gcp import common, samples, snippets
from synthtool.log import logger
from pathlib import Path
from typing import Any, Optional, Dict, List

JAR_DOWNLOAD_URL = "https://github.com/google/google-java-format/releases/download/google-java-format-{version}/google-java-format-{version}-all-deps.jar"
DEFAULT_FORMAT_VERSION = "1.7"
GOOD_LICENSE = """
/*
 * Copyright 2020 Google LLC
 *
 * Licensed under the Apache License, Version 2.0 (the "License");
 * you may not use this file except in compliance with the License.
 * You may obtain a copy of the License at
 *
 *     https://www.apache.org/licenses/LICENSE-2.0
 *
 * Unless required by applicable law or agreed to in writing, software
 * distributed under the License is distributed on an "AS IS" BASIS,
 * WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
 * See the License for the specific language governing permissions and
 * limitations under the License.
 */
"""
PROTOBUF_HEADER = "// Generated by the protocol buffer compiler.  DO NOT EDIT!"
BAD_LICENSE = """/\\*
 \\* Copyright \\d{4} Google LLC
 \\*
 \\* Licensed under the Apache License, Version 2.0 \\(the "License"\\); you may not use this file except
 \\* in compliance with the License. You may obtain a copy of the License at
 \\*
 \\* http://www.apache.org/licenses/LICENSE-2.0
 \\*
 \\* Unless required by applicable law or agreed to in writing, software distributed under the License
 \\* is distributed on an "AS IS" BASIS, WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express
 \\* or implied. See the License for the specific language governing permissions and limitations under
 \\* the License.
 \\*/
"""
DEFAULT_MIN_SUPPORTED_JAVA_VERSION = 7


def format_code(
    path: str, version: str = DEFAULT_FORMAT_VERSION, times: int = 2
) -> None:
    """
    Runs the google-java-format jar against all .java files found within the
    provided path.
    """
    jar_name = f"google-java-format-{version}.jar"
    jar = cache.get_cache_dir() / jar_name
    if not jar.exists():
        _download_formatter(version, jar)

    # Find all .java files in path and run the formatter on them
    files = list(glob.iglob(os.path.join(path, "**/*.java"), recursive=True))

    # Run the formatter as a jar file
    logger.info("Running java formatter on {} files".format(len(files)))
    for _ in range(times):
        shell.run(["java", "-jar", str(jar), "--replace"] + files)


def _download_formatter(version: str, dest: Path) -> None:
    logger.info("Downloading java formatter")
    url = JAR_DOWNLOAD_URL.format(version=version)
    response = requests.get(url)
    response.raise_for_status()
    with open(dest, "wb") as fh:
        fh.write(response.content)


def fix_proto_headers(proto_root: Path) -> None:
    s.replace(
        [proto_root / "src/**/*.java"],
        PROTOBUF_HEADER,
        f"{GOOD_LICENSE}{PROTOBUF_HEADER}",
    )
    # https://github.com/googleapis/gapic-generator/issues/3074
    s.replace(
        [proto_root / "src/**/*Name.java", proto_root / "src/**/*Names.java"],
        BAD_LICENSE,
        GOOD_LICENSE,
    )


def fix_grpc_headers(grpc_root: Path, package_name: str) -> None:
    s.replace(
        [grpc_root / "src/**/*.java"], "^package (.*);", f"{GOOD_LICENSE}package \\1;",
    )


def latest_maven_version(group_id: str, artifact_id: str) -> Optional[str]:
    """Helper function to find the latest released version of a Maven artifact.

    Fetches metadata from Maven Central and parses out the latest released
    version.

    Args:
        group_id (str): The groupId of the Maven artifact
        artifact_id (str): The artifactId of the Maven artifact

    Returns:
        The latest version of the artifact as a string or None
    """
    group_path = "/".join(group_id.split("."))
    url = (
        f"https://repo1.maven.org/maven2/{group_path}/{artifact_id}/maven-metadata.xml"
    )
    response = requests.get(url)
    if response.status_code >= 400:
        return "0.0.0"

    return version_from_maven_metadata(response.text)


def version_from_maven_metadata(metadata: str) -> Optional[str]:
    """Helper function to parse the latest released version from the Maven
    metadata XML file.

    Args:
        metadata (str): The XML contents of the Maven metadata file

    Returns:
        The latest version of the artifact as a string or None
    """
    root = ET.fromstring(metadata)
    latest = root.find("./versioning/latest")
    if latest is not None:
        return latest.text

    return None


def _common_generation(
    service: str,
    version: str,
    library: Path,
    package_pattern: str,
    suffix: str = "",
    destination_name: str = None,
    cloud_api: bool = True,
):
    """Helper function to execution the common generation cleanup actions.

    Fixes headers for protobuf classes and generated gRPC stub services. Copies
    code and samples to their final destinations by convention. Runs the code
    formatter on the generated code.

    Args:
        service (str): Name of the service.
        version (str): Service API version.
        library (Path): Path to the temp directory with the generated library.
        package_pattern (str): Package name template for fixing file headers.
        suffix (str, optional): Suffix that the generated library folder. The
            artman output differs from bazel's output directory. Defaults to "".
        destination_name (str, optional): Override the service name for the
            destination of the output code. Defaults to the service name.
    """

    if destination_name is None:
        destination_name = service

    cloud_prefix = "cloud-" if cloud_api else ""
    package_name = package_pattern.format(service=service, version=version)
    fix_proto_headers(
        library / f"proto-google-{cloud_prefix}{service}-{version}{suffix}"
    )
    fix_grpc_headers(
        library / f"grpc-google-{cloud_prefix}{service}-{version}{suffix}", package_name
    )

    s.copy(
        [library / f"gapic-google-{cloud_prefix}{service}-{version}{suffix}/src"],
        f"google-{cloud_prefix}{destination_name}/src",
        required=True,
    )
    s.copy(
        [library / f"grpc-google-{cloud_prefix}{service}-{version}{suffix}/src"],
        f"grpc-google-{cloud_prefix}{destination_name}-{version}/src",
        required=True,
    )
    s.copy(
        [library / f"proto-google-{cloud_prefix}{service}-{version}{suffix}/src"],
        f"proto-google-{cloud_prefix}{destination_name}-{version}/src",
        required=True,
    )

    format_code(f"google-{cloud_prefix}{destination_name}/src")
    format_code(f"grpc-google-{cloud_prefix}{destination_name}-{version}/src")
    format_code(f"proto-google-{cloud_prefix}{destination_name}-{version}/src")


def gapic_library(
    service: str,
    version: str,
    config_pattern: str = "/google/cloud/{service}/artman_{service}_{version}.yaml",
    package_pattern: str = "com.google.cloud.{service}.{version}",
    gapic: gcp.GAPICGenerator = None,
    destination_name: str = None,
    **kwargs,
) -> Path:
    """Generate a Java library using the gapic-generator via artman via Docker.

    Generates code into a temp directory, fixes missing header fields, and
    copies into the expected locations.

    Args:
        service (str): Name of the service.
        version (str): Service API version.
        config_pattern (str, optional): Path template to artman config YAML
            file. Defaults to "/google/cloud/{service}/artman_{service}_{version}.yaml"
        package_pattern (str, optional): Package name template for fixing file
            headers. Defaults to "com.google.cloud.{service}.{version}".
        gapic (GAPICGenerator, optional): Generator instance.
        destination_name (str, optional): Override the service name for the
            destination of the output code. Defaults to the service name.
        **kwargs: Additional options for gapic.java_library()

    Returns:
        The path to the temp directory containing the generated client.
    """

    if gapic is None:
        gapic = gcp.GAPICGenerator()

    library = gapic.java_library(
        service=service,
        version=version,
        config_path=config_pattern.format(service=service, version=version),
        artman_output_name="",
        include_samples=True,
        **kwargs,
    )

    _common_generation(
        service=service,
        version=version,
        library=library,
        package_pattern=package_pattern,
        destination_name=destination_name,
    )

    return library


def bazel_library(
    service: str,
    version: str,
    package_pattern: str = "com.google.cloud.{service}.{version}",
    gapic: gcp.GAPICBazel = None,
    destination_name: str = None,
    cloud_api: bool = True,
    **kwargs,
) -> Path:
    """Generate a Java library using the gapic-generator via bazel.

    Generates code into a temp directory, fixes missing header fields, and
    copies into the expected locations.

    Args:
        service (str): Name of the service.
        version (str): Service API version.
        package_pattern (str, optional): Package name template for fixing file
            headers. Defaults to "com.google.cloud.{service}.{version}".
        gapic (GAPICBazel, optional): Generator instance.
        destination_name (str, optional): Override the service name for the
            destination of the output code. Defaults to the service name.
        **kwargs: Additional options for gapic.java_library()

    Returns:
        The path to the temp directory containing the generated client.
    """
    if gapic is None:
        gapic = gcp.GAPICBazel()

    library = gapic.java_library(service=service, version=version, **kwargs)

    cloud_prefix = "cloud-" if cloud_api else ""
    _common_generation(
        service=service,
        version=version,
        library=library / f"google-{cloud_prefix}{service}-{version}-java",
        package_pattern=package_pattern,
        suffix="-java",
        destination_name=destination_name,
        cloud_api=cloud_api,
    )

    return library


def _merge_common_templates(
    source_text: str, destination_text: str, file_path: Path
) -> str:
    # keep any existing pom.xml
    if file_path.match("pom.xml"):
        logger.debug(f"existing pom file found ({file_path}) - keeping the existing")
        return destination_text

    # by default return the newly generated content
    return source_text

def _common_template_metadata() -> Dict[str, Any]:
    metadata = {}  # type: Dict[str, Any]
    repo_metadata = common._load_repo_metadata()
    if repo_metadata:
        metadata["repo"] = repo_metadata
        group_id, artifact_id = repo_metadata["distribution_name"].split(":")

        metadata["latest_version"] = latest_maven_version(
            group_id=group_id, artifact_id=artifact_id
        )

    metadata["latest_bom_version"] = latest_maven_version(
        group_id="com.google.cloud", artifact_id="libraries-bom",
    )

    metadata["samples"] = samples.all_samples(["samples/**/src/main/java/**/*.java"])
    metadata["snippets"] = snippets.all_snippets(
        ["samples/**/src/main/java/**/*.java", "samples/**/pom.xml"]
    )
    if repo_metadata and "min_java_version" in repo_metadata:
        metadata["min_java_version"] = repo_metadata["min_java_version"]
    else:
        metadata["min_java_version"] = DEFAULT_MIN_SUPPORTED_JAVA_VERSION
    
    return metadata


def common_templates(
    excludes: List[str] = [], template_path: Optional[Path] = None, **kwargs
) -> None:
    """Generate common templates for a Java Library

    Fetches information about the repository from the .repo-metadata.json file,
    information about the latest artifact versions and copies the files into
    their expected location.

    Args:
        excludes (List[str], optional): List of template paths to ignore
        **kwargs: Additional options for CommonTemplates.java_library()
    """
    kwargs["metadata"] = _common_template_metadata()
    templates = gcp.CommonTemplates(template_path=template_path).java_library(**kwargs)

    # README.md is now synthesized separately. This prevents synthtool from deleting the
    # README as it's no longer generated here.
    excludes.append("README.md")

    s.copy([templates], excludes=excludes, merge=_merge_common_templates)

def custom_templates(files: List[str], **kwargs) -> None:
    """Generate custom template files

    Fetches information about the repository from the .repo-metadata.json file,
    information about the latest artifact versions and copies the files into
    their expected location.

    Args:
        files (List[str], optional): List of template paths to include
        **kwargs: Additional options for CommonTemplates.render()
    """
    kwargs["metadata"] = _common_template_metadata()
    for file in files:
        template = gcp.CommonTemplates().render(file, **kwargs)
        s.copy([template])
