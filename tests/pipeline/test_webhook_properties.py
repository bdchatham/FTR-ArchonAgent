"""Property-based tests for GitHub webhook event parsing.

This module contains property-based tests using Hypothesis to verify that
the webhook handler correctly parses GitHub issue events across all valid
input combinations.

**Validates: Requirements 1.3, 1.5**

Feature: agent-orchestration

Testing Configuration:
- Library: Hypothesis (Python)
- Minimum iterations: 100 per property test
- Tag format: Feature: agent-orchestration, Property N: <property_text>
"""

from hypothesis import given, settings, strategies as st, assume

from src.pipeline.webhook import WebhookHandler, GitHubIssueEvent, IssueAction


# =============================================================================
# Hypothesis Strategies for Generating Valid GitHub Payloads
# =============================================================================


@st.composite
def valid_github_username(draw: st.DrawFn) -> str:
    """Generate a valid GitHub username.

    GitHub usernames:
    - Can contain alphanumeric characters and hyphens
    - Cannot start or end with a hyphen
    - Cannot have consecutive hyphens
    - Are 1-39 characters long
    """
    # Use a simpler strategy that generates valid usernames
    username = draw(
        st.text(
            alphabet=st.sampled_from(
                "abcdefghijklmnopqrstuvwxyzABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789-"
            ),
            min_size=1,
            max_size=39,
        ).filter(
            lambda x: (
                x.strip()
                and not x.startswith("-")
                and not x.endswith("-")
                and "--" not in x
            )
        )
    )
    return username


@st.composite
def valid_repo_name(draw: st.DrawFn) -> str:
    """Generate a valid GitHub repository name.

    Repository names:
    - Can contain alphanumeric characters, hyphens, underscores, and periods
    - Cannot start with a period
    - Are 1-100 characters long
    """
    name = draw(
        st.text(
            alphabet=st.sampled_from(
                "abcdefghijklmnopqrstuvwxyzABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789-_."
            ),
            min_size=1,
            max_size=100,
        ).filter(lambda x: x.strip() and not x.startswith("."))
    )
    return name


@st.composite
def valid_label_name(draw: st.DrawFn) -> str:
    """Generate a valid GitHub label name.

    Labels can contain most characters but we focus on common patterns.
    """
    return draw(
        st.text(
            alphabet=st.sampled_from(
                "abcdefghijklmnopqrstuvwxyzABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789-_: "
            ),
            min_size=1,
            max_size=50,
        ).filter(lambda x: x.strip())
    )


@st.composite
def valid_issue_title(draw: st.DrawFn) -> str:
    """Generate a valid issue title.

    Issue titles must be non-empty strings. We include unicode to test
    internationalization support.
    """
    # Generate text with printable characters including unicode
    title = draw(
        st.text(min_size=1, max_size=200).filter(lambda x: x.strip())
    )
    return title


@st.composite
def valid_issue_body(draw: st.DrawFn) -> str:
    """Generate a valid issue body.

    Issue bodies can be empty or contain any text including unicode,
    markdown, and code blocks.
    """
    # Body can be empty or contain text
    return draw(st.text(max_size=10000))


@st.composite
def github_issue_payload(draw: st.DrawFn) -> dict:
    """Generate a valid GitHub issue webhook payload.

    This strategy generates payloads that conform to the GitHub webhook
    structure for issue events with actions: opened, edited, or labeled.

    Returns:
        A dictionary representing a valid GitHub issue webhook payload.
    """
    action = draw(st.sampled_from(["opened", "edited", "labeled"]))
    issue_number = draw(st.integers(min_value=1, max_value=1000000))
    title = draw(valid_issue_title())
    body = draw(valid_issue_body())
    labels = draw(st.lists(valid_label_name(), max_size=20))
    repo_name = draw(valid_repo_name())
    owner = draw(valid_github_username())
    author = draw(valid_github_username())

    return {
        "action": action,
        "issue": {
            "number": issue_number,
            "title": title,
            "body": body,
            "labels": [{"name": label} for label in labels],
            "user": {"login": author},
        },
        "repository": {
            "name": repo_name,
            "owner": {"login": owner},
        },
    }


@st.composite
def github_issue_payload_with_null_body(draw: st.DrawFn) -> dict:
    """Generate a valid GitHub issue payload with null body.

    GitHub allows issues with null body field, which should be handled
    gracefully by the parser.
    """
    action = draw(st.sampled_from(["opened", "edited", "labeled"]))
    issue_number = draw(st.integers(min_value=1, max_value=1000000))
    title = draw(valid_issue_title())
    labels = draw(st.lists(valid_label_name(), max_size=20))
    repo_name = draw(valid_repo_name())
    owner = draw(valid_github_username())
    author = draw(valid_github_username())

    return {
        "action": action,
        "issue": {
            "number": issue_number,
            "title": title,
            "body": None,  # Explicitly null body
            "labels": [{"name": label} for label in labels],
            "user": {"login": author},
        },
        "repository": {
            "name": repo_name,
            "owner": {"login": owner},
        },
    }


# =============================================================================
# Property Tests
# =============================================================================


class TestIssueEventParsing:
    """Property tests for issue event parsing.

    Feature: agent-orchestration, Property 1: Issue Event Parsing

    *For any* valid GitHub issue event payload with action `opened`, `edited`,
    or `labeled`, the webhook handler SHALL successfully parse the event into
    a structured `GitHubIssueEvent` object.

    **Validates: Requirements 1.3, 1.5**
    """

    @given(payload=github_issue_payload())
    @settings(max_examples=100)
    def test_valid_payload_parses_successfully(self, payload: dict) -> None:
        """Property 1: Issue Event Parsing

        *For any* valid GitHub issue event payload with action `opened`,
        `edited`, or `labeled`, the webhook handler SHALL successfully parse
        the event into a structured `GitHubIssueEvent` object.

        **Validates: Requirements 1.3**
        """
        handler = WebhookHandler(secret="test-secret")
        result = handler.parse_issue_event(payload)

        # The handler should successfully parse valid payloads
        assert result is not None, (
            f"Failed to parse valid payload with action={payload['action']}, "
            f"issue_number={payload['issue']['number']}"
        )
        assert isinstance(result, GitHubIssueEvent)

    @given(payload=github_issue_payload())
    @settings(max_examples=100)
    def test_parsed_action_matches_payload(self, payload: dict) -> None:
        """Verify parsed action matches the original payload action.

        **Validates: Requirements 1.3**
        """
        handler = WebhookHandler(secret="test-secret")
        result = handler.parse_issue_event(payload)

        assert result is not None
        assert result.action.value == payload["action"]

    @given(payload=github_issue_payload_with_null_body())
    @settings(max_examples=100)
    def test_null_body_handled_gracefully(self, payload: dict) -> None:
        """Property 1 edge case: Null body should be handled gracefully.

        GitHub allows issues with null body field. The parser should
        convert this to an empty string.

        **Validates: Requirements 1.3**
        """
        handler = WebhookHandler(secret="test-secret")
        result = handler.parse_issue_event(payload)

        assert result is not None
        assert result.body == ""  # Null body should become empty string


class TestIssueFieldExtraction:
    """Property tests for issue field extraction.

    Feature: agent-orchestration, Property 2: Issue Field Extraction

    *For any* parsed GitHub issue event, the extracted data SHALL include all
    required fields: issue number, title, body, labels, repository, and author,
    with values matching the original payload.

    **Validates: Requirements 1.3, 1.5**
    """

    @given(payload=github_issue_payload())
    @settings(max_examples=100)
    def test_issue_number_matches_payload(self, payload: dict) -> None:
        """Property 2: Issue number extraction matches original payload.

        **Validates: Requirements 1.5**
        """
        handler = WebhookHandler(secret="test-secret")
        result = handler.parse_issue_event(payload)

        assert result is not None
        assert result.issue_number == payload["issue"]["number"]

    @given(payload=github_issue_payload())
    @settings(max_examples=100)
    def test_title_matches_payload(self, payload: dict) -> None:
        """Property 2: Issue title extraction matches original payload.

        **Validates: Requirements 1.5**
        """
        handler = WebhookHandler(secret="test-secret")
        result = handler.parse_issue_event(payload)

        assert result is not None
        # Title is stripped by the handler
        assert result.title == payload["issue"]["title"].strip()

    @given(payload=github_issue_payload())
    @settings(max_examples=100)
    def test_body_matches_payload(self, payload: dict) -> None:
        """Property 2: Issue body extraction matches original payload.

        **Validates: Requirements 1.5**
        """
        handler = WebhookHandler(secret="test-secret")
        result = handler.parse_issue_event(payload)

        assert result is not None
        expected_body = payload["issue"]["body"]
        if expected_body is None:
            expected_body = ""
        assert result.body == expected_body

    @given(payload=github_issue_payload())
    @settings(max_examples=100)
    def test_labels_match_payload(self, payload: dict) -> None:
        """Property 2: Issue labels extraction matches original payload.

        **Validates: Requirements 1.5**
        """
        handler = WebhookHandler(secret="test-secret")
        result = handler.parse_issue_event(payload)

        assert result is not None
        expected_labels = [
            label["name"].strip() for label in payload["issue"]["labels"]
        ]
        assert result.labels == expected_labels

    @given(payload=github_issue_payload())
    @settings(max_examples=100)
    def test_repository_matches_payload(self, payload: dict) -> None:
        """Property 2: Repository name extraction matches original payload.

        **Validates: Requirements 1.5**
        """
        handler = WebhookHandler(secret="test-secret")
        result = handler.parse_issue_event(payload)

        assert result is not None
        assert result.repository == payload["repository"]["name"].strip()

    @given(payload=github_issue_payload())
    @settings(max_examples=100)
    def test_owner_matches_payload(self, payload: dict) -> None:
        """Property 2: Repository owner extraction matches original payload.

        **Validates: Requirements 1.5**
        """
        handler = WebhookHandler(secret="test-secret")
        result = handler.parse_issue_event(payload)

        assert result is not None
        assert result.owner == payload["repository"]["owner"]["login"].strip()

    @given(payload=github_issue_payload())
    @settings(max_examples=100)
    def test_author_matches_payload(self, payload: dict) -> None:
        """Property 2: Issue author extraction matches original payload.

        **Validates: Requirements 1.5**
        """
        handler = WebhookHandler(secret="test-secret")
        result = handler.parse_issue_event(payload)

        assert result is not None
        assert result.author == payload["issue"]["user"]["login"].strip()

    @given(payload=github_issue_payload())
    @settings(max_examples=100)
    def test_all_required_fields_present(self, payload: dict) -> None:
        """Property 2: All required fields are present in parsed event.

        *For any* parsed GitHub issue event, the extracted data SHALL include
        all required fields: issue number, title, body, labels, repository,
        and author.

        **Validates: Requirements 1.5**
        """
        handler = WebhookHandler(secret="test-secret")
        result = handler.parse_issue_event(payload)

        assert result is not None

        # Verify all required fields are present and have correct types
        assert isinstance(result.action, IssueAction)
        assert isinstance(result.issue_number, int)
        assert result.issue_number > 0
        assert isinstance(result.title, str)
        assert len(result.title) > 0
        assert isinstance(result.body, str)  # Can be empty but must be string
        assert isinstance(result.labels, list)
        assert all(isinstance(label, str) for label in result.labels)
        assert isinstance(result.repository, str)
        assert len(result.repository) > 0
        assert isinstance(result.owner, str)
        assert len(result.owner) > 0
        assert isinstance(result.author, str)
        assert len(result.author) > 0


class TestEdgeCases:
    """Edge case tests for webhook parsing.

    These tests verify that the parser handles edge cases correctly,
    including unicode content, empty bodies, and many labels.

    **Validates: Requirements 1.3, 1.5**
    """

    @given(
        action=st.sampled_from(["opened", "edited", "labeled"]),
        issue_number=st.integers(min_value=1, max_value=1000000),
        owner=valid_github_username(),
        repo_name=valid_repo_name(),
        author=valid_github_username(),
    )
    @settings(max_examples=100)
    def test_empty_body_handled(
        self,
        action: str,
        issue_number: int,
        owner: str,
        repo_name: str,
        author: str,
    ) -> None:
        """Edge case: Empty body string should be preserved.

        **Validates: Requirements 1.5**
        """
        payload = {
            "action": action,
            "issue": {
                "number": issue_number,
                "title": "Test issue",
                "body": "",
                "labels": [],
                "user": {"login": author},
            },
            "repository": {
                "name": repo_name,
                "owner": {"login": owner},
            },
        }

        handler = WebhookHandler(secret="test-secret")
        result = handler.parse_issue_event(payload)

        assert result is not None
        assert result.body == ""

    @given(
        action=st.sampled_from(["opened", "edited", "labeled"]),
        issue_number=st.integers(min_value=1, max_value=1000000),
        owner=valid_github_username(),
        repo_name=valid_repo_name(),
        author=valid_github_username(),
        num_labels=st.integers(min_value=10, max_value=20),
    )
    @settings(max_examples=100)
    def test_many_labels_handled(
        self,
        action: str,
        issue_number: int,
        owner: str,
        repo_name: str,
        author: str,
        num_labels: int,
    ) -> None:
        """Edge case: Many labels should be handled correctly.

        **Validates: Requirements 1.5**
        """
        labels = [f"label-{i}" for i in range(num_labels)]
        payload = {
            "action": action,
            "issue": {
                "number": issue_number,
                "title": "Test issue with many labels",
                "body": "Body text",
                "labels": [{"name": label} for label in labels],
                "user": {"login": author},
            },
            "repository": {
                "name": repo_name,
                "owner": {"login": owner},
            },
        }

        handler = WebhookHandler(secret="test-secret")
        result = handler.parse_issue_event(payload)

        assert result is not None
        assert len(result.labels) == num_labels
        assert result.labels == labels

    @given(
        action=st.sampled_from(["opened", "edited", "labeled"]),
        issue_number=st.integers(min_value=1, max_value=1000000),
        owner=valid_github_username(),
        repo_name=valid_repo_name(),
        author=valid_github_username(),
    )
    @settings(max_examples=100)
    def test_unicode_title_handled(
        self,
        action: str,
        issue_number: int,
        owner: str,
        repo_name: str,
        author: str,
    ) -> None:
        """Edge case: Unicode in title should be preserved.

        **Validates: Requirements 1.5**
        """
        unicode_title = "🐛 Bug: 日本語テスト émojis and ñ"
        payload = {
            "action": action,
            "issue": {
                "number": issue_number,
                "title": unicode_title,
                "body": "Body with unicode: 中文 العربية",
                "labels": [],
                "user": {"login": author},
            },
            "repository": {
                "name": repo_name,
                "owner": {"login": owner},
            },
        }

        handler = WebhookHandler(secret="test-secret")
        result = handler.parse_issue_event(payload)

        assert result is not None
        assert result.title == unicode_title
        assert "中文" in result.body
        assert "العربية" in result.body

    @given(
        action=st.sampled_from(["opened", "edited", "labeled"]),
        issue_number=st.integers(min_value=1, max_value=1000000),
        owner=valid_github_username(),
        repo_name=valid_repo_name(),
        author=valid_github_username(),
    )
    @settings(max_examples=100)
    def test_empty_labels_list_handled(
        self,
        action: str,
        issue_number: int,
        owner: str,
        repo_name: str,
        author: str,
    ) -> None:
        """Edge case: Empty labels list should result in empty list.

        **Validates: Requirements 1.5**
        """
        payload = {
            "action": action,
            "issue": {
                "number": issue_number,
                "title": "Issue without labels",
                "body": "Body text",
                "labels": [],
                "user": {"login": author},
            },
            "repository": {
                "name": repo_name,
                "owner": {"login": owner},
            },
        }

        handler = WebhookHandler(secret="test-secret")
        result = handler.parse_issue_event(payload)

        assert result is not None
        assert result.labels == []

    @given(payload=github_issue_payload())
    @settings(max_examples=100)
    def test_issue_id_format_correct(self, payload: dict) -> None:
        """Verify issue_id property returns correct format.

        The issue_id should be in format "{owner}/{repository}#{issue_number}".

        **Validates: Requirements 1.5**
        """
        handler = WebhookHandler(secret="test-secret")
        result = handler.parse_issue_event(payload)

        assert result is not None

        expected_id = (
            f"{payload['repository']['owner']['login'].strip()}/"
            f"{payload['repository']['name'].strip()}#"
            f"{payload['issue']['number']}"
        )
        assert result.issue_id == expected_id

    @given(payload=github_issue_payload())
    @settings(max_examples=100)
    def test_full_repository_format_correct(self, payload: dict) -> None:
        """Verify full_repository property returns correct format.

        The full_repository should be in format "{owner}/{repository}".

        **Validates: Requirements 1.5**
        """
        handler = WebhookHandler(secret="test-secret")
        result = handler.parse_issue_event(payload)

        assert result is not None

        expected_repo = (
            f"{payload['repository']['owner']['login'].strip()}/"
            f"{payload['repository']['name'].strip()}"
        )
        assert result.full_repository == expected_repo
