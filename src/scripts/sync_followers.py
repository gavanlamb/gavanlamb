"""Keep the authenticated GitHub user's followers and following lists in sync."""

import os
import sys


API_ROOT = "https://api.github.com"
AUTHENTICATED_USER_URL = f"{API_ROOT}/user"
FOLLOWERS_URL = f"{API_ROOT}/user/followers"
FOLLOWING_URL = f"{API_ROOT}/user/following"
FOLLOW_USER_URL = f"{API_ROOT}/user/following/{{username}}"
API_VERSION = "2026-03-10"
PER_PAGE = 100
REQUEST_TIMEOUT = 30


class GitHubSyncError(RuntimeError):
    """Raised when the sync cannot safely continue."""


def create_session(requests_module, token):
    """Create an authenticated Requests session for the GitHub REST API."""
    session = requests_module.Session()
    session.headers.update(
        {
            "Accept": "application/vnd.github+json",
            "Authorization": f"Bearer {token}",
            "X-GitHub-Api-Version": API_VERSION,
            "User-Agent": "gavanlamb-follower-sync",
        }
    )
    return session


def _response_message(response):
    """Return GitHub's error message without including request credentials."""
    try:
        payload = response.json()
    except (AttributeError, ValueError):
        payload = None

    if isinstance(payload, dict) and payload.get("message"):
        return str(payload["message"])

    return "No error details were returned."


def _require_status(response, expected_status, action):
    """Raise a useful, non-secret-bearing error for an unexpected API status."""
    if response.status_code == expected_status:
        return

    hint = ""
    if response.status_code == 401:
        hint = " The token is invalid, expired, or revoked."
    elif response.status_code == 403:
        hint = " Check the token's Followers permission and GitHub rate limits."

    raise GitHubSyncError(
        f"{action} failed with GitHub API status {response.status_code}: "
        f"{_response_message(response)}{hint}"
    )


def get_authenticated_username(session):
    """Return the login belonging to the supplied token."""
    response = session.get(AUTHENTICATED_USER_URL, timeout=REQUEST_TIMEOUT)
    _require_status(response, 200, "Authenticating the token")

    try:
        payload = response.json()
    except ValueError as error:
        raise GitHubSyncError(
            "GitHub returned invalid JSON while authenticating the token."
        ) from error

    login = payload.get("login") if isinstance(payload, dict) else None
    if not isinstance(login, str) or not login:
        raise GitHubSyncError(
            "GitHub's authenticated-user response did not contain a login."
        )

    return login


def get_paginated_results(session, url):
    """Fetch a complete result set, raising rather than returning partial data."""
    results = []
    page = 1

    while True:
        response = session.get(
            url,
            params={"page": page, "per_page": PER_PAGE},
            timeout=REQUEST_TIMEOUT,
        )
        _require_status(response, 200, f"Fetching {url}")

        try:
            data = response.json()
        except ValueError as error:
            raise GitHubSyncError(
                f"GitHub returned invalid JSON while fetching {url}."
            ) from error

        if not isinstance(data, list):
            raise GitHubSyncError(
                f"GitHub returned an unexpected response while fetching {url}."
            )

        results.extend(data)
        if len(data) < PER_PAGE:
            return results

        page += 1


def _get_logins(session, url, description):
    print(f"Fetching {description}...")
    logins = []

    for user in get_paginated_results(session, url):
        login = user.get("login") if isinstance(user, dict) else None
        if not isinstance(login, str) or not login:
            raise GitHubSyncError(
                f"GitHub returned a {description} entry without a login."
            )
        logins.append(login)

    return logins


def get_followers(session):
    """Get every user following the authenticated user."""
    return _get_logins(session, FOLLOWERS_URL, "followers")


def get_following(session):
    """Get every user followed by the authenticated user."""
    return _get_logins(session, FOLLOWING_URL, "following")


def follow_user(session, username):
    """Follow a user, failing the run if GitHub rejects the mutation."""
    url = FOLLOW_USER_URL.format(username=username)
    response = session.put(url, data=b"", timeout=REQUEST_TIMEOUT)
    _require_status(response, 204, f"Following {username}")
    print(f"Followed: {username}")


def unfollow_user(session, username):
    """Unfollow a user, failing the run if GitHub rejects the mutation."""
    url = FOLLOW_USER_URL.format(username=username)
    response = session.delete(url, timeout=REQUEST_TIMEOUT)
    _require_status(response, 204, f"Unfollowing {username}")
    print(f"Unfollowed: {username}")


def parse_excluded_accounts(value):
    """Parse exclusions into case-insensitive GitHub logins."""
    return {
        account.strip().casefold()
        for account in value.split(",")
        if account.strip()
    }


def sync_followers_and_following(session, excluded_accounts=None):
    """Synchronise followers and following after both complete reads succeed."""
    excluded_accounts = excluded_accounts or set()

    followers = get_followers(session)
    following = get_following(session)

    followers_by_key = {login.casefold(): login for login in followers}
    following_by_key = {login.casefold(): login for login in following}

    users_to_follow = sorted(
        set(followers_by_key) - set(following_by_key),
        key=str.casefold,
    )
    users_to_unfollow = sorted(
        set(following_by_key) - set(followers_by_key) - excluded_accounts,
        key=str.casefold,
    )

    if users_to_follow:
        print(f"Following {len(users_to_follow)} new users...")
        for key in users_to_follow:
            follow_user(session, followers_by_key[key])
    else:
        print("You're already following all your followers!")

    if users_to_unfollow:
        print(
            f"Unfollowing {len(users_to_unfollow)} users who don't follow you back..."
        )
        for key in users_to_unfollow:
            unfollow_user(session, following_by_key[key])
    else:
        print("No users to unfollow or excluded from unfollowing.")


def run_from_environment():
    """Validate configuration and perform one synchronisation run."""
    token = os.getenv("GITHUB_TOKEN", "").strip()
    if not token:
        raise GitHubSyncError(
            "GITHUB_TOKEN is not set. Configure the GH_PAT_TOKEN repository secret."
        )

    # Imported here so configuration errors can be tested without third-party packages.
    import requests

    session = create_session(requests, token)
    authenticated_username = get_authenticated_username(session)
    expected_username = os.getenv("EXPECTED_GITHUB_USERNAME", "").strip()

    if (
        expected_username
        and authenticated_username.casefold() != expected_username.casefold()
    ):
        raise GitHubSyncError(
            "The token belongs to "
            f"{authenticated_username}, not the expected account {expected_username}."
        )

    print(f"Authenticated as {authenticated_username}.")
    excluded_accounts = parse_excluded_accounts(
        os.getenv("EXCLUDED_ACCOUNTS", "")
    )
    sync_followers_and_following(session, excluded_accounts)


def main():
    try:
        run_from_environment()
    except GitHubSyncError as error:
        print(f"::error::{error}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
