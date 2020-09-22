from __future__ import absolute_import

import os
import sys
from hashlib import md5

import six
import pytest

pytest_plugins = ["sentry.utils.pytest"]

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "src"))


def pytest_configure(config):
    import warnings

    # XXX(dcramer): Kombu throws a warning due to transaction.commit_manually
    # being used
    warnings.filterwarnings("error", "", Warning, r"^(?!(|kombu|raven|sentry))")

    # always install plugins for the tests
    install_sentry_plugins()

    config.addinivalue_line("markers", "obsolete: mark test as obsolete and soon to be removed")


def install_sentry_plugins():
    # Sentry's pytest plugin explicitly doesn't load plugins, so let's load all of them
    # and ignore the fact that we're not *just* testing our own
    # Note: We could manually register/configure INSTALLED_APPS by traversing our entry points
    # or package directories, but this is easier assuming Sentry doesn't change APIs.
    # Note: Order of operations matters here.
    from sentry.runner.importer import install_plugin_apps
    from django.conf import settings

    install_plugin_apps("sentry.apps", settings)

    from sentry.runner.initializer import register_plugins

    register_plugins(settings, raise_on_plugin_load_failure=True)

    settings.ASANA_CLIENT_ID = "abc"
    settings.ASANA_CLIENT_SECRET = "123"
    settings.BITBUCKET_CONSUMER_KEY = "abc"
    settings.BITBUCKET_CONSUMER_SECRET = "123"
    settings.GITHUB_APP_ID = "abc"
    settings.GITHUB_API_SECRET = "123"
    # this isn't the real secret
    settings.SENTRY_OPTIONS["github.integration-hook-secret"] = "b3002c3e321d4b7880360d397db2ccfd"


def pytest_collection_modifyitems(config, items):
    """
    After collection, we need to:

    - Filter tests that subclass SnubaTestCase as tests in `tests/acceptance` are not being marked as `snuba`
    - Select tests based on group and group strategy

    """

    total_groups = int(os.environ.get("TOTAL_TEST_GROUPS", 1))
    current_group = int(os.environ.get("TEST_GROUP", 0))
    grouping_strategy = os.environ.get("TEST_GROUP_STRATEGY", "file")

    accepted, keep, discard = [], [], []

    for index, item in enumerate(items):
        # XXX: For some reason tests in `tests/acceptance` are not being
        # marked as snuba, so deselect test cases not a subclass of SnubaTestCase
        if os.environ.get("RUN_SNUBA_TESTS_ONLY"):
            from sentry.testutils import SnubaTestCase
            import inspect

            if inspect.isclass(item.cls) and not issubclass(item.cls, SnubaTestCase):
                # No need to group if we are deselecting this
                discard.append(item)
                continue
            accepted.append(item)
        else:
            accepted.append(item)

        # In the case where we group by round robin (e.g. TEST_GROUP_STRATEGY is not `file`),
        # we want to only include items in `accepted` list

        # TODO(joshuarli): six 1.12.0 adds ensure_binary: six.ensure_binary(item.location[0])
        item_to_group = (
            int(md5(six.text_type(item.location[0]).encode("utf-8")).hexdigest(), 16)
            if grouping_strategy == "file"
            else len(accepted) - 1
        )

        # Split tests in different groups
        group_num = item_to_group % total_groups
        marker = "group_%s" % group_num
        config.addinivalue_line("markers", marker)
        item.add_marker(getattr(pytest.mark, marker))

        if group_num == current_group:
            keep.append(item)
        else:
            discard.append(item)

    # This only needs to be done if there are items to be de-selected
    if len(discard) > 0:
        items[:] = keep
        config.hook.pytest_deselected(items=discard)
