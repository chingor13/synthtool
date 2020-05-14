#!/usr/bin/env python3.6

"""Synthesizes multiple libraries and reports status."""

import argparse
import functools
import importlib
import os
import requests
import subprocess
import sys
import typing

import jinja2
import yaml

from autosynth import executor, github, synth
from autosynth.log import logger


def _execute(command: typing.List[str], env: typing.Dict) -> typing.Tuple[int, bytes]:
    """Helper to wrap command invocation for testing"""
    result = executor.run(
        command=command,
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        check=False,
        encoding="utf-8",
        env=env,
    )
    return (result.returncode, result.stdout)


def synthesize_library(
    library: typing.Dict,
    github_token: str,
    extra_args: typing.List[str],
    runner: typing.Callable[
        [typing.List[str], typing.Dict], typing.Tuple[int, bytes]
    ] = _execute,
) -> typing.Dict:
    """Run autosynth on a single library.

    Arguments:
        library {dict} - Library configuration

    """
    logger.info(f"Synthesizing {library['name']}.")

    command = [sys.executable, "-m", "autosynth.synth"]

    env = os.environ
    env["GITHUB_TOKEN"] = github_token

    library_args = [
        "--repository",
        library["repository"],
        "--synth-path",
        library.get("synth-path", ""),
        "--branch-suffix",
        library.get("branch-suffix", ""),
        "--pr-title",
        library.get("pr-title", ""),
    ]

    if library.get("metadata-path"):
        library_args.extend(["--metadata-path", library.get("metadata-path")])

    if library.get("deprecated-execution", False):
        library_args.append("--deprecated-execution")

    # run autosynth in a separate process
    (returncode, output) = runner(command, env)
    error = returncode not in (0, synth.EXIT_CODE_SKIPPED)
    skipped = returncode == synth.EXIT_CODE_SKIPPED
    if error:
        logger.error(f"Synthesis failed for {library['name']}")
    return {
        "name": library["name"],
        "output": output,
        "error": error,
        "skipped": skipped,
    }


def make_report(name: str, results: typing.List[typing.Dict]) -> None:
    """Write an xunit report sponge_log.xml to the current directory.

    Arguments:
        name {str} - Name of the report
        results {typing.List[typing.Dict]} - List of synth results
    """
    with open("report.xml.j2") as fh:
        template = jinja2.Template(fh.read())

    output = template.render(
        name=name,
        failures=len([result for result in results if result["error"]]),
        skips=len([result for result in results if result["skipped"]]),
        results=results,
    )

    with open("sponge_log.xml", "w") as fh:
        fh.write(output)


@functools.lru_cache()
def _list_issues_cached(gh, *args, **kwargs):
    """A caching wrapper for listing issues, so we don't expend our quota."""
    return list(gh.list_issues(*args, **kwargs))


def _close_issue(gh, repository: str, existing_issue: dict):
    if existing_issue is None:
        return

    logger.info(f"Closing issue: {existing_issue['url']}")
    gh.create_issue_comment(
        repository,
        issue_number=existing_issue["number"],
        comment="Autosynth passed, closing! :green_heart:",
    )
    gh.patch_issue(
        repository, issue_number=existing_issue["number"], state="closed",
    )


def _file_or_comment_on_issue(
    gh, name: str, repository: str, issue_title: str, existing_issue: dict, output: str
):
    message = f"""\
Here's the output from running `synth.py`:

```
{output}
```

Google internal developers can see the full log [here](https://sponge/{os.environ.get('KOKORO_BUILD_ID')}).
"""

    if not existing_issue:
        issue_details = (
            f"Hello! Autosynth couldn't regenerate {name}. :broken_heart:\n\n{message}"
        )
        labels = ["autosynth failure", "priority: p1", "type: bug"]

        api_label = gh.get_api_label(repository, name)
        if api_label:
            labels.append(api_label)

        issue = gh.create_issue(
            repository, title=issue_title, body=issue_details, labels=labels,
        )
        logger.info(f"Opened issue: {issue['url']}")

    # otherwise leave a comment on the existing issue.
    else:
        comment_body = (
            f"Autosynth is still having trouble generating {name}. :sob:\n\n{message}"
        )

        gh.create_issue_comment(
            repository, issue_number=existing_issue["number"], comment=comment_body,
        )
        logger.info(f"Updated issue: {existing_issue['url']}")


def report_to_github(gh, name: str, repository: str, error: bool, output: str) -> None:
    """Update GitHub with the status of the autosynth run.

    On failure, will either open a new issue or comment on an existing issue. On
    success, will close any open autosynth issues.

    Arguments:
        name {str} - Name of the library
        repository {str} - GitHub repository with the format [owner]/[repo]
        error {bool} - Whether or not the autosynth run failed
        output {str} - Output of the individual autosynth run
    """
    issue_title = f"Synthesis failed for {name}"

    # Get a list of all open autosynth failure issues, and check if there's
    # an existing one.
    open_issues = _list_issues_cached(
        gh, repository, state="open", label="autosynth failure"
    )
    existing_issues = [issue for issue in open_issues if issue["title"] == issue_title]
    existing_issue = existing_issues[0] if len(existing_issues) else None

    # If successful, close any outstanding issues for synthesizing this
    # library.
    if not error:
        _close_issue(gh, repository, existing_issue)
    # Otherwise, file an issue or comment on an existing issue for synthesis.
    else:
        _file_or_comment_on_issue(
            gh, name, repository, issue_title, existing_issue, output
        )


def load_config(
    config: str,
) -> typing.Optional[typing.List[typing.Dict[str, typing.Any]]]:
    """Load configuration from either a configuration YAML or from a module.

    If a yaml path is provided, it must return a top level "libraries" entry
    which contains a list of repository definitions.

    If a module is provided, it will invoke list_repositories() on the
    module which should return a list of repository definitions.

    A repository definition is a dictionary which contains:
    * name {str} -- Required. The name of the repo/client
    * repository {str} -- Required. GitHub repository with the format [owner]/[repo]
    * synth-path {str} -- Optional. Path within the repository to the synth.py file.
    * branch-suffix {str} -- Optional. When opening a pull request, use this suffix for
        branch name
    * metadata-path {str} -- Optional. Path to location of synth.metadata file.
    * deprecated-execution {bool} -- Optional. If set, will invoke synthtool with the
        synthtool binary rather than as a module. Defaults to False.
    * no_create_issue {bool} -- Optional. If set, will not manage GitHub issues when
        autosynth fails for any reason. Defaults to False.

    Arguments:
        config {str} -- Path to configuration YAML or module name

    Returns:
        List[Dict[str, Any]] - List of library configurations to synthesize
        None - The configuration file doesn't exist and no module found
    """
    if os.path.exists(config):
        with open(config) as fh:
            return yaml.load(fh)["libraries"]
    else:
        try:
            provider = importlib.import_module(config)
            return provider.list_repositories()  # type: ignore
        except (ImportError, AttributeError):
            pass
    return None


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--config")
    parser.add_argument("--github-token", default=os.environ.get("GITHUB_TOKEN"))
    parser.add_argument("extra_args", nargs=argparse.REMAINDER)

    args = parser.parse_args()

    config = load_config(args.config)
    if config is None:
        sys.exit("No configuration could be loaded.")

    gh = github.GitHub(args.github_token)

    results = []
    for library in config:
        result = synthesize_library(library, args.github_token, args.extra_args[1:])
        results.append(result)

        if library.get("no_create_issue"):
            continue

        try:
            report_to_github(
                gh=gh,
                name=library["name"],
                repository=library["repository"],
                error=result["error"],
                output=result["output"],
            )
        except requests.HTTPError:
            # ignore as GitHub commands already log errors on failure
            pass

    make_report(args.config, results)

    num_failures = len([result for result in results if result["error"]])
    if num_failures > 0:
        logger.error(f"Failed to synthesize {num_failures} job(s).")
        sys.exit(1)


if __name__ == "__main__":
    main()
