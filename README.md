# Archon - System Documentation RAG Chat Bot

Archon is a production-grade Retrieval-Augmented Generation (RAG) system that monitors `.kiro/` documentation in public GitHub repositories and provides intelligent query capabilities for engineers and agents. Built with AWS CDK (TypeScript), LangChain, and AWS Bedrock, Archon serves as a system engineering expert to help teams understand their product architecture.

The infrastructure follows AWS Well-Architected Framework best practices for operational excellence, security, reliability, performance efficiency, and cost optimization.

## Overview

Archon consists of two independent systems:

1. **Document Monitor (Cron Job)** - Asynchronously monitors configured GitHub repositories for `.kiro/` documentation changes, generates embeddings, and populates a vector database
2. **Query Agent (API)** - Processes natural language queries using RAG to retrieve relevant documentation and generate contextual answers with source references

<!-- Test webhook trigger 2 -->

## Architecture

```
┌─────────────────────────────────────────────────────────────┐
│  Configuration (config.yaml)                                │
│  - GitHub repositories to monitor                           │
│  - Model configurations (embeddings, LLM)                   │
│  - Infrastructure parameters                                │
└─────────────────────────────────────────────────────────────┘
                              │
                ┌─────────────┴─────────────┐
                ▼                           ▼
    ┌───────────────────────┐   ┌───────────────────────┐
    │  Cron Job Stack       │   │  Agent Stack          │
    │  - EventBridge        │   │  - API Gateway        │
    │  - Monitor Lambda     │   │  - Query Lambda       │
    │  - DynamoDB Tracker   │   │  - LangChain RAG      │
    └───────────────────────┘   └───────────────────────┘
                │                           │
                └─────────────┬─────────────┘
                              ▼
                ┌───────────────────────────┐
                │  Shared Resources         │
                │  - OpenSearch Serverless  │
                │  - AWS Bedrock            │
                └───────────────────────────┘
```

## Key Features

- **Configuration-Driven**: All repository sources and infrastructure parameters defined in YAML
- **Automatic Monitoring**: Scheduled cron job detects and processes documentation changes
- **Vector Search**: Semantic search using AWS Bedrock embeddings (Titan) and OpenSearch Serverless
- **Intelligent Responses**: Claude 3 Haiku generates contextual answers with source citations
- **Independent Stacks**: Separate CloudFormation stacks for monitoring and query processing
- **Extensible Design**: Built to support future code crawling and multi-modal features

## Technology Stack

- **Infrastructure**: AWS CDK (TypeScript)
- **Compute**: AWS Lambda (Python 3.11)
- **Orchestration**: LangChain
- **Vector Database**: Amazon OpenSearch Serverless
- **Embeddings**: AWS Bedrock (amazon.titan-embed-text-v1)
- **LLM**: AWS Bedrock (anthropic.claude-3-haiku-20240307)
- **API**: Amazon API Gateway (REST)
- **Scheduling**: Amazon EventBridge
- **State Management**: Amazon DynamoDB
- **GitHub Integration**: PyGithub library

## Prerequisites

- AWS Account with appropriate permissions
- AWS CLI configured
- Node.js 18+ (for CDK)
- Python 3.11+
- AWS CDK CLI installed (`npm install -g aws-cdk`)
- Access to AWS Bedrock models in your region

## Project Structure

```
archon/
├── .kiro/                      # Agent-readable documentation
│   └── specs/
│       └── archon-rag-system/
│           ├── requirements.md
│           ├── design.md
│           └── tasks.md
├── bin/                        # CDK app entry point
│   └── archon.ts
├── lib/                        # CDK stack definitions
│   ├── shared-resources.ts
│   ├── cron-stack.ts
│   ├── agent-stack.ts
│   └── config-loader.ts
├── lambda/                     # Lambda function code
│   ├── monitor/               # Document monitoring Lambda
│   │   ├── handler.py
│   │   ├── document_monitor.py
│   │   ├── github_client.py
│   │   ├── change_tracker.py
│   │   └── ingestion_pipeline.py
│   └── query/                 # Query processing Lambda
│       ├── handler.py
│       ├── query_handler.py
│       └── rag_chain.py
├── config/                     # Configuration files
│   ├── config.yaml            # Main configuration
│   └── config.example.yaml    # Example configuration
├── tests/                      # Test files
│   ├── unit/
│   └── property/              # Property-based tests
├── cdk.json                    # CDK configuration
├── requirements.txt            # Python dependencies
├── package.json                # Node.js dependencies
└── README.md                   # This file
```

## Configuration

Create a `config/config.yaml` file with your repository sources and infrastructure parameters:

```yaml
version: "1.0"

repositories:
  - url: "https://github.com/your-org/repo1"
    branch: "main"
    paths: [".kiro/"]
  - url: "https://github.com/your-org/repo2"
    branch: "main"
    paths: [".kiro/"]

infrastructure:
  cron_schedule: "rate(1 hour)"
  lambda_memory: 1024
  lambda_timeout: 300
  vector_db_dimensions: 1536

models:
  embedding_model: "amazon.titan-embed-text-v1"
  llm_model: "anthropic.claude-3-haiku-20240307"
  llm_temperature: 0.7
  max_tokens: 2048
  retrieval_k: 5
```

## Installation

1. **Clone the repository**
   ```bash
   git clone <repository-url>
   cd archon
   ```

2. **Install Node.js dependencies**
   ```bash
   npm install
   ```

3. **Install Python dependencies**
   ```bash
   pip install -r requirements.txt
   ```

4. **Configure AWS credentials**
   ```bash
   aws configure
   ```

5. **Bootstrap CDK (first time only)**
   ```bash
   cdk bootstrap
   ```

## Deployment

### Automated Deployment (Recommended)

Archon uses **Argo Workflows** for CI/CD pipeline automation. The pipeline handles:
- Building Lambda layers
- Running property-based tests
- CDK synthesis and validation
- Multi-environment deployment (dev → staging → prod)
- Rollback capabilities
- Integration with monitoring

See the Argo Workflows pipeline specification for details (coming soon).

### Manual Deployment (Local Development)

For local development and testing:

1. **Create your configuration file**
   ```bash
   cp config/config.example.yaml config/config.yaml
   # Edit config.yaml with your repository sources
   ```

2. **Build Lambda layer** (first time or when dependencies change)
   ```bash
   ./scripts/build-lambda-layer.sh
   ```

3. **Synthesize CloudFormation templates**
   ```bash
   cdk synth
   ```

4. **Deploy all stacks**
   ```bash
   cdk deploy --all
   ```

   Or deploy stacks individually:
   ```bash
   cdk deploy ArchonInfrastructure-dev
   cdk deploy ArchonKnowledgeBase-dev
   cdk deploy ArchonAgent-dev
   ```

5. **Deploy to specific environment**
   ```bash
   cdk deploy --all --context environment=staging
   ```

6. **Note the API Gateway endpoint** from the deployment output

### Deployment Verification

After deployment, verify the system is working:

```bash
# Check Lambda functions are deployed
aws lambda list-functions --query 'Functions[?starts_with(FunctionName, `archon-`)].FunctionName'

# Check API Gateway endpoint
aws apigateway get-rest-apis --query 'items[?name==`archon-api-dev`].{id:id,name:name}'

# Test the query endpoint
curl -X POST https://<api-id>.execute-api.<region>.amazonaws.com/dev/v1/chat/completions \
  -H "Content-Type: application/json" \
  -d '{"messages": [{"role": "user", "content": "What is Archon?"}]}'
```

## Usage

### Querying Archon

Send a POST request to the API Gateway endpoint:

```bash
curl -X POST https://<api-id>.execute-api.<region>.amazonaws.com/prod/query \
  -H "Content-Type: application/json" \
  -d '{
    "query": "How does the authentication system work?",
    "max_results": 5
  }'
```

Response:
```json
{
  "answer": "The authentication system uses...",
  "sources": [
    {
      "repo": "github.com/org/repo1",
      "file_path": ".kiro/architecture/auth.md",
      "relevance_score": 0.92
    }
  ],
  "timestamp": "2025-12-09T10:30:00Z",
  "query": "How does the authentication system work?"
}
```

### Manual Cron Job Trigger

Trigger the document monitor manually:

```bash
aws lambda invoke \
  --function-name ArchonCron-MonitorFunction \
  --payload '{}' \
  response.json
```

## Development

### Running Tests

```bash
# Run all tests
pytest

# Run property-based tests
pytest tests/property/

# Run with coverage
pytest --cov=lambda --cov-report=html
```

### Local Development

For local Lambda testing:

```bash
# Install development dependencies
pip install -r requirements-dev.txt

# Run Lambda locally with SAM
sam local invoke MonitorFunction -e events/cron-event.json
```

## Monitoring

### CloudWatch Dashboards

Access the Archon dashboard in CloudWatch to monitor:
- Lambda invocations and errors
- API Gateway request metrics
- DynamoDB operations
- OpenSearch query performance

### CloudWatch Alarms

Pre-configured alarms for:
- Lambda function errors
- API Gateway 5xx errors
- DynamoDB throttling
- High query latency

### X-Ray Tracing

Enable X-Ray tracing to visualize request flows through:
- API Gateway → Query Lambda → Bedrock → OpenSearch

## Troubleshooting

### Common Issues

**Issue**: Lambda timeout during document processing
- **Solution**: Increase `lambda_timeout` in config.yaml or reduce batch size

**Issue**: Bedrock throttling errors
- **Solution**: Implement request batching or request service quota increase

**Issue**: OpenSearch connection errors
- **Solution**: Verify VPC configuration and security group rules

**Issue**: GitHub API rate limiting
- **Solution**: Reduce `cron_schedule` frequency or use GitHub authentication

### Logs

View Lambda logs:
```bash
# Monitor logs
aws logs tail /aws/lambda/ArchonCron-MonitorFunction --follow

# Query logs
aws logs tail /aws/lambda/ArchonAgent-QueryFunction --follow
```

## Cost Optimization

- **Cron Schedule**: Adjust monitoring frequency based on documentation update patterns
- **Lambda Memory**: Right-size based on actual usage (monitor CloudWatch metrics)
- **OpenSearch**: Use serverless tier for variable workloads
- **Bedrock**: Claude Haiku is cost-effective for most use cases

## Security

- All repositories must be public (no authentication required)
- IAM roles follow least-privilege principle
- API Gateway can be configured with API keys or AWS IAM authentication
- No credentials stored in vector database
- VPC isolation available for enhanced security

## Future Enhancements

- **Code Crawling**: Extend beyond `.kiro/` to index source code
- **Multi-Modal Support**: Process diagrams and images in documentation
- **Conversation History**: Support multi-turn dialogues
- **Hybrid Search**: Combine semantic and keyword search
- **User Feedback**: Collect and analyze answer quality ratings

## Contributing

See `.kiro/specs/archon-rag-system/` for detailed requirements, design, and implementation tasks.

## License

[Your License Here]

## Support

For issues and questions:
- Check the troubleshooting section above
- Review CloudWatch logs and metrics
- Consult `.kiro/` documentation for technical details

# Webhook Test
Testing pipeline webhook integration with fixed EventListener - Mon Jan 12 15:06:41 PST 2026
# Test webhook trigger - Tue Jan 13 08:34:45 PST 2026


