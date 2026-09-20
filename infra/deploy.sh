#!/usr/bin/env bash
# One-command deploy of the ContextForge backend to AWS using the AWS SAM CLI.
#
#   cd infra && ./deploy.sh [stack-name]
#
# Prereqs (see infra/README.md):
#   1. AWS SAM CLI installed                          <- you have this
#   2. AWS credentials configured                     <- you have this
#   3. Bedrock model access enabled for Anthropic     <- one-time console step
#
# Optional env vars:
#   AWS_REGION                   default: us-east-1
#   BEDROCK_MODEL_ID             default: us.anthropic.claude-haiku-4-5-20251001-v1:0 (cheap, vision-capable)
#   BEDROCK_EMBEDDING_MODEL_ID   default: amazon.titan-embed-text-v2:0
#   GROQ_API_KEY                 default: "" (optional; only for LLM_PROVIDER=groq)
set -euo pipefail
cd "$(dirname "$0")"

STACK="${1:-contextforge}"
REGION="${AWS_REGION:-us-east-1}"

./build_lambda.sh

echo "==> Packaging Lambda code (SAM auto-creates the deployment bucket)"
sam package \
  --region "${REGION}" \
  --template-file template.yaml \
  --output-template-file packaged.yaml \
  --resolve-s3

echo "==> Deploying stack '${STACK}' in ${REGION} (takes ~2-3 minutes)"
# sam deploy rejects empty values in --parameter-overrides, so only pass what is set
OVERRIDES=(
  "BedrockModelId=${BEDROCK_MODEL_ID:-us.anthropic.claude-haiku-4-5-20251001-v1:0}"
  "BedrockEmbeddingModelId=${BEDROCK_EMBEDDING_MODEL_ID:-amazon.titan-embed-text-v2:0}"
)
if [ -n "${GROQ_API_KEY:-}" ]; then
  OVERRIDES+=("GroqApiKey=${GROQ_API_KEY}")
fi

sam deploy \
  --region "${REGION}" \
  --template-file packaged.yaml \
  --stack-name "${STACK}" \
  --capabilities CAPABILITY_IAM \
  --no-confirm-changeset \
  --parameter-overrides "${OVERRIDES[@]}"

echo ""
echo "==> Deployment outputs:"
aws cloudformation describe-stacks \
  --stack-name "${STACK}" --region "${REGION}" \
  --query "Stacks[0].Outputs" --output table

echo ""
echo "Next:"
echo "  ./smoke_test.sh <ApiUrl from the table above>"
