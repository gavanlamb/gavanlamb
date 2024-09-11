import requests
import os

# GitHub token and username from environment variables
GITHUB_TOKEN = os.getenv('GITHUB_TOKEN')
GITHUB_USERNAME = os.getenv('GITHUB_ACTOR')

# Excluded accounts (provided as a comma-separated string)
EXCLUDED_ACCOUNTS = os.getenv('EXCLUDED_ACCOUNTS', '').split(',')

# GitHub API endpoints
FOLLOWERS_URL = f'https://api.github.com/users/{GITHUB_USERNAME}/followers'
FOLLOWING_URL = f'https://api.github.com/users/{GITHUB_USERNAME}/following'
FOLLOW_USER_URL = 'https://api.github.com/user/following/{username}'

# Headers for GitHub API authentication
headers = {
    'Authorization': f'token {GITHUB_TOKEN}',
    'Accept': 'application/vnd.github.v3+json'
}

def get_followers():
    """Get the list of users following you."""
    response = requests.get(FOLLOWERS_URL, headers=headers)
    if response.status_code == 200:
        return [user['login'] for user in response.json()]
    else:
        print(f"Error fetching followers: {response.status_code}")
        return []

def get_following():
    """Get the list of users you are following."""
    response = requests.get(FOLLOWING_URL, headers=headers)
    if response.status_code == 200:
        return [user['login'] for user in response.json()]
    else:
        print(f"Error fetching following: {response.status_code}")
        return []

def follow_user(username):
    """Follow a user on GitHub."""
    url = FOLLOW_USER_URL.format(username=username)
    response = requests.put(url, headers=headers)
    if response.status_code == 204:
        print(f"Followed: {username}")
    else:
        print(f"Error following {username}: {response.status_code}")

def unfollow_user(username):
    """Unfollow a user on GitHub."""
    url = FOLLOW_USER_URL.format(username=username)
    response = requests.delete(url, headers=headers)
    if response.status_code == 204:
        print(f"Unfollowed: {username}")
    else:
        print(f"Error unfollowing {username}: {response.status_code}")

def sync_followers_and_following():
    """Sync followers with who you are following and handle unfollowing."""
    followers = get_followers()
    following = get_following()

    # Follow users who are following you but whom you're not yet following
    users_to_follow = set(followers) - set(following)

    if users_to_follow:
        print(f"Following {len(users_to_follow)} new users...")
        for user in users_to_follow:
            follow_user(user)
    else:
        print("You're already following all your followers!")

    # Unfollow users who you're following but who don't follow you back (excluding those in the exclusion list)
    users_to_unfollow = set(following) - set(followers) - set(EXCLUDED_ACCOUNTS)

    if users_to_unfollow:
        print(f"Unfollowing {len(users_to_unfollow)} users who don't follow you back...")
        for user in users_to_unfollow:
            unfollow_user(user)
    else:
        print("No users to unfollow or excluded from unfollowing.")

if __name__ == "__main__":
    sync_followers_and_following()
