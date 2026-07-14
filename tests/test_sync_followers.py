import os
import unittest
from unittest.mock import Mock, call, patch

from src.scripts import sync_followers


def response(status_code, payload=None):
    mock_response = Mock()
    mock_response.status_code = status_code
    mock_response.json.return_value = payload
    return mock_response


class PaginationTests(unittest.TestCase):
    def test_pagination_returns_every_page(self):
        session = Mock()
        first_page = [{"login": f"user-{index}"} for index in range(100)]
        second_page = [{"login": "last-user"}]
        session.get.side_effect = [
            response(200, first_page),
            response(200, second_page),
        ]

        result = sync_followers.get_paginated_results(session, "https://example.test")

        self.assertEqual(result, first_page + second_page)
        self.assertEqual(
            session.get.call_args_list,
            [
                call(
                    "https://example.test",
                    params={"page": 1, "per_page": 100},
                    timeout=30,
                ),
                call(
                    "https://example.test",
                    params={"page": 2, "per_page": 100},
                    timeout=30,
                ),
            ],
        )

    def test_first_page_authentication_failure_raises(self):
        session = Mock()
        session.get.return_value = response(401, {"message": "Bad credentials"})

        with self.assertRaisesRegex(
            sync_followers.GitHubSyncError, "invalid, expired, or revoked"
        ):
            sync_followers.get_paginated_results(session, "https://example.test")

    def test_later_page_failure_does_not_return_partial_data(self):
        session = Mock()
        session.get.side_effect = [
            response(200, [{"login": f"user-{index}"} for index in range(100)]),
            response(500, {"message": "Server error"}),
        ]

        with self.assertRaisesRegex(
            sync_followers.GitHubSyncError, "status 500"
        ):
            sync_followers.get_paginated_results(session, "https://example.test")


class SyncTests(unittest.TestCase):
    @patch.object(sync_followers, "unfollow_user")
    @patch.object(sync_followers, "follow_user")
    @patch.object(sync_followers, "get_following")
    @patch.object(sync_followers, "get_followers")
    def test_sync_applies_exact_changes_and_honours_exclusions(
        self, get_followers, get_following, follow_user, unfollow_user
    ):
        session = Mock()
        get_followers.return_value = ["Alice", "bob", "mutual"]
        get_following.return_value = ["bob", "carol", "Keep"]

        sync_followers.sync_followers_and_following(
            session, {"keep"}
        )

        self.assertEqual(
            follow_user.call_args_list,
            [call(session, "Alice"), call(session, "mutual")],
        )
        unfollow_user.assert_called_once_with(session, "carol")

    @patch.object(sync_followers, "unfollow_user")
    @patch.object(sync_followers, "follow_user")
    @patch.object(sync_followers, "get_following")
    @patch.object(sync_followers, "get_followers")
    def test_sync_is_a_noop_for_matching_case_insensitive_sets(
        self, get_followers, get_following, follow_user, unfollow_user
    ):
        session = Mock()
        get_followers.return_value = ["Alice"]
        get_following.return_value = ["alice"]

        sync_followers.sync_followers_and_following(session)

        follow_user.assert_not_called()
        unfollow_user.assert_not_called()

    @patch.object(sync_followers, "unfollow_user")
    @patch.object(sync_followers, "follow_user")
    @patch.object(sync_followers, "get_following")
    @patch.object(sync_followers, "get_followers")
    def test_sync_makes_no_changes_when_a_read_fails(
        self, get_followers, get_following, follow_user, unfollow_user
    ):
        session = Mock()
        get_followers.return_value = ["alice"]
        get_following.side_effect = sync_followers.GitHubSyncError("read failed")

        with self.assertRaisesRegex(sync_followers.GitHubSyncError, "read failed"):
            sync_followers.sync_followers_and_following(session)

        follow_user.assert_not_called()
        unfollow_user.assert_not_called()


class MutationTests(unittest.TestCase):
    def test_follow_failure_raises(self):
        session = Mock()
        session.put.return_value = response(403, {"message": "Forbidden"})

        with self.assertRaisesRegex(
            sync_followers.GitHubSyncError, "Followers permission"
        ):
            sync_followers.follow_user(session, "alice")

    def test_unfollow_failure_raises(self):
        session = Mock()
        session.delete.return_value = response(500, {"message": "Server error"})

        with self.assertRaisesRegex(
            sync_followers.GitHubSyncError, "status 500"
        ):
            sync_followers.unfollow_user(session, "alice")


class ConfigurationTests(unittest.TestCase):
    def test_missing_token_returns_nonzero_without_importing_requests(self):
        with patch.dict(os.environ, {}, clear=True):
            self.assertEqual(sync_followers.main(), 1)

    def test_token_owner_must_match_expected_account(self):
        fake_requests = Mock()
        fake_session = Mock()
        fake_requests.Session.return_value = fake_session
        fake_session.get.return_value = response(200, {"login": "someone-else"})

        with (
            patch.dict(
                os.environ,
                {
                    "GITHUB_TOKEN": "secret",
                    "EXPECTED_GITHUB_USERNAME": "gavanlamb",
                },
                clear=True,
            ),
            patch.dict("sys.modules", {"requests": fake_requests}),
        ):
            self.assertEqual(sync_followers.main(), 1)

        fake_session.put.assert_not_called()
        fake_session.delete.assert_not_called()


if __name__ == "__main__":
    unittest.main()
