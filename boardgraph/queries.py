"""Documentos GraphQL do board.

Ponto crítico: as datas do board (Start/Target date) são *issue fields*
(`ProjectV2ItemIssueFieldValue` → `IssueFieldDateValue`), não campos de
projeto clássicos. O fragmento `ProjectV2ItemFieldDateValue` continua aqui
como fallback para boards que usem o campo antigo.
"""

from __future__ import annotations

ISSUE_DEPENDENCIES = """
              blockedBy(first: 50) {
                totalCount
                nodes { number title state url repository { nameWithOwner } }
              }
              parent { number title }
"""

FIELD_VALUES = """
          fieldValues(first: 25) {
            nodes {
              __typename
              ... on ProjectV2ItemFieldDateValue {
                date
                field { ... on ProjectV2FieldCommon { name } }
              }
              ... on ProjectV2ItemFieldTextValue {
                text
                field { ... on ProjectV2FieldCommon { name } }
              }
              ... on ProjectV2ItemFieldNumberValue {
                number
                field { ... on ProjectV2FieldCommon { name } }
              }
              ... on ProjectV2ItemFieldSingleSelectValue {
                name
                field { ... on ProjectV2FieldCommon { name } }
              }
              ... on ProjectV2ItemFieldIterationValue {
                title
                startDate
                duration
                field { ... on ProjectV2FieldCommon { name } }
              }
              ... on ProjectV2ItemFieldMilestoneValue {
                milestone { number title dueOn }
                field { ... on ProjectV2FieldCommon { name } }
              }
              ... on ProjectV2ItemIssueFieldValue {
                issueFieldValue {
                  ... on IssueFieldDateValue {
                    value
                    field { ... on IssueFieldDate { name } }
                  }
                  ... on IssueFieldNumberValue {
                    value
                    field { ... on IssueFieldNumber { name } }
                  }
                  ... on IssueFieldTextValue {
                    value
                    field { ... on IssueFieldText { name } }
                  }
                  ... on IssueFieldSingleSelectValue {
                    value
                    field { ... on IssueFieldSingleSelect { name } }
                  }
                }
              }
            }
          }
"""


def board_query(include_deps: bool = True, include_body: bool = False) -> str:
    deps = ISSUE_DEPENDENCIES if include_deps else ""
    body = "body" if include_body else ""
    return f"""
query Board($owner: String!, $number: Int!, $cursor: String, $filter: String) {{
  rateLimit {{ remaining cost resetAt }}
  organization(login: $owner) {{
    projectV2(number: $number) {{
      id
      title
      url
      fields(first: 50) {{
        nodes {{
          __typename
          ... on ProjectV2FieldCommon {{ id name dataType }}
          ... on ProjectV2SingleSelectField {{ options {{ id name }} }}
          ... on ProjectV2IterationField {{
            configuration {{ iterations {{ id title startDate duration }} }}
          }}
        }}
      }}
      items(first: 100, after: $cursor, query: $filter) {{
        totalCount
        pageInfo {{ hasNextPage endCursor }}
        nodes {{
          id
          createdAt
          updatedAt
{_indent(FIELD_VALUES, 10)}
          content {{
            __typename
            ... on Issue {{
              number
              title
              url
              state
              createdAt
              updatedAt
              closedAt
              {body}
              repository {{ nameWithOwner }}
              milestone {{ number title dueOn state closedAt }}
              labels(first: 20) {{ nodes {{ name }} }}
              assignees(first: 10) {{ nodes {{ login }} }}
{deps}
            }}
            ... on PullRequest {{
              number
              title
              url
              state
              createdAt
              updatedAt
              closedAt
              mergedAt
              repository {{ nameWithOwner }}
              milestone {{ number title dueOn state closedAt }}
              assignees(first: 10) {{ nodes {{ login }} }}
            }}
            ... on DraftIssue {{
              title
              {body}
              createdAt
            }}
          }}
        }}
      }}
    }}
  }}
}}
"""


def _indent(block: str, spaces: int) -> str:
    pad = " " * spaces
    return "\n".join(pad + line if line.strip() else line for line in block.strip("\n").splitlines())
