#!/usr/bin/env bash
set -euo pipefail

artifact_id=${1:?Provide the Pages artifact ID}
artifact_name=${2:?Provide the Pages artifact name}

# Upload finalization can precede visibility in the workflow's artifact list.
for attempt in {1..12}; do
    if gh api --method GET "repos/$GITHUB_REPOSITORY/actions/runs/$GITHUB_RUN_ID/artifacts" \
        -f name="$artifact_name" | jq -e --arg id "$artifact_id" \
        '.artifacts | any((.id | tostring) == $id and .expired == false)' > /dev/null; then
        echo "GitHub Actions can list the Pages artifact ($artifact_id)."
        exit 0
    fi
    if [ "$attempt" -lt 12 ]; then
        sleep 5
    fi
done

echo "::error::GitHub Actions did not list Pages artifact $artifact_name ($artifact_id)."
exit 1
