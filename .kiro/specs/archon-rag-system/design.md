# Design Document

## Overview

Archon is a production-grade RAG-based system documentation chat bot that monitors .kiro/ documentation in public GitHub repositories and provides intelligent query capabilities for engineers and agents. The system consists of two independent CloudFormation stacks: a Cron Job Stack for asynchronous document ingestion and an Agent Stack for query processing. The architecture leverages AWS Bedrock for embeddings and language model inference, LangChain for RAG orchestration, and AWS CDK for infrastructure as code.

The system follows a configuration-driven approach where repository sources and infrastructure parameters are defined in static YAML/JSON files, enabling declarative infrastructure management and easy extensibility for future enhancements like code crawling.

## Architecture

### High-Level Architecture

```
┌─────────────────────────────────────────────────────────────────┐
│                     Configuration Layer                          │
│  (config.yaml: repos, models, schedules, infrastructure params) │
└─────────────────────────────────────────────────────────────────┘
                              │
                              ├──────────────────┬─────────────────┐
                              ▼                  ▼                 ▼
┌──────────────────────────────────┐  ┌──────────────────────────────────┐
│     Cron Job Stack (CDK)         │  │      Agent Stack (CDK)           │
│  ┌────────────────────────────┐  │  │  ┌────────────────────────────┐  │
│  │  EventBridge Rule (Cron)   │  │  │  │   API Gateway (REST)       │  │
│  └────────────┬───────────────┘  │  │  └────────────┬───────────────┘  │
│               ▼                   │  │               ▼                   │
│  ┌────────────────────────────┐  │  │  ┌────────────────────────────┐  │
│  │  Lambda: Document Monitor  │  │  │  │  Lambda: Query Handler     │  │
│  │  - Fetch .kiro/ docs       │  │  │  │  - LangChain RAG chain     │  │
│  │  - Detect changes          │  │  │  │  - Bedrock integration     │  │
│  │  - Generate embeddings     │  │  │  │  - Response formatting     │  │
│  └────────────┬───────────────┘  │  │  └────────────┬───────────────┘  │
│               ▼                   │  │               ▼                   │
│  ┌────────────────────────────┐  │  │  ┌────────────────────────────┐  │
│  │  DynamoDB: Change Tracker  │  │  │  │  CloudWatch Logs           │  │
│  └────────────────────────────┘  │  │  └────────────────────────────┘  │
└──────────────┬───────────────────┘  └──────────────┬───────────────────┘
               │                                      │
               └──────────────┬───────────────────────┘
                              ▼
                ┌──────────────────────────────┐
                │  Shared Resources            │
                │  ┌────────────────────────┐  │
                │  │  OpenSearch Serverless │  │
                │  │  (Vector Database)     │  │
                │  └────────────────────────┘  │
                │  ┌────────────────────────┐  │
                │  │  AWS Bedrock           │  │
                │  │  - Embeddings Model    │  │
                │  │  - LLM (Claude/Titan)  │  │
                │  └────────────────────────┘  │
                └──────────────────────────────┘
```

### Stack Separation

**Cron Job Stack:**
- EventBridge scheduled rule
- Lambda function for document monitoring
- DynamoDB table for change tracking
- IAM roles and policies
- CloudWatch log groups

**Agent Stack:**
- API Gateway REST API
- Lambda function for query processing
- IAM roles and policies
- CloudWatch log groups

**Shared Resources:**
- OpenSearch Serverless collection (vector database)
- AWS Bedrock access (managed service)
- VPC and networking (if required)

### Technology Stack

- **Infrastructure:** AWS CDK (TypeScript)
- **Compute:** AWS Lambda (Python 3.11)
- **Orchestration:** LangChain
- **Vector Database:** Amazon OpenSearch Serverless
- **Embeddings:** AWS Bedrock (amazon.titan-embed-text-v1)
- **LLM:** AWS Bedrock (anthropic.claude-3-haiku-20240307)
- **API:** Amazon API Gateway (REST)
- **Scheduling:** Amazon EventBridge
- **State Management:** Amazon DynamoDB
- **Configuration:** YAML files

## Components and Interfaces

### 1. Configuration Manager

**Purpose:** Load and validate configuration from static YAML files

**Interface:**
```python
class ConfigManager:
    def load_config(self, config_path: str) -> Config
    def validate_config(self, config: Config) -> bool
    def get_repositories(self) -> List[RepositoryConfig]
    def get_infrastructure_params(self) -> InfrastructureConfig
    def get_model_config(self) -> ModelConfig
```

**Configuration Schema:**
```yaml
version: "1.0"
repositories:
  - url: "https://github.com/org/repo1"
    branch: "main"
    paths: [".kiro/"]
  - url: "https://github.com/org/repo2"
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

### 2. Document Monitor (Cron Job Lambda)

**Purpose:** Periodically check configured repositories for .kiro/ document changes

**Interface:**
```python
class DocumentMonitor:
    def __init__(self, config: Config, github_client: GitHubClient, 
                 change_tracker: ChangeTracker, ingestion_pipeline: IngestionPipeline)
    
    def execute(self) -> MonitoringResult
    def fetch_repository_contents(self, repo: RepositoryConfig) -> List[Document]
    def detect_changes(self, documents: List[Document]) -> List[Document]
    def process_changed_documents(self, documents: List[Document]) -> None
```

**Handler:**
```python
def lambda_handler(event, context):
    # Load configuration
    # Initialize components
    # Execute monitoring
    # Return results
```

### 3. GitHub Client

**Purpose:** Interface with GitHub API to retrieve repository contents

**Interface:**
```python
class GitHubClient:
    def __init__(self, rate_limiter: RateLimiter)
    
    def get_directory_contents(self, repo_url: str, path: str, branch: str) -> List[FileMetadata]
    def get_file_content(self, repo_url: str, file_path: str, branch: str) -> str
    def get_file_sha(self, repo_url: str, file_path: str, branch: str) -> str
    def validate_repository_access(self, repo_url: str) -> bool
```

### 4. Change Tracker

**Purpose:** Track document versions to detect changes

**Interface:**
```python
class ChangeTracker:
    def __init__(self, dynamodb_table: str)
    
    def get_last_known_sha(self, repo: str, file_path: str) -> Optional[str]
    def update_sha(self, repo: str, file_path: str, sha: str, timestamp: datetime) -> None
    def has_changed(self, repo: str, file_path: str, current_sha: str) -> bool
```

**DynamoDB Schema:**
```
Table: archon-document-tracker
Partition Key: repo_file_path (String) - format: "{repo_url}#{file_path}"
Attributes:
  - sha (String)
  - last_modified (String - ISO timestamp)
  - last_checked (String - ISO timestamp)
  - content_hash (String)
```

### 5. Ingestion Pipeline

**Purpose:** Process documents and store in vector database

**Interface:**
```python
class IngestionPipeline:
    def __init__(self, embeddings: Embeddings, vector_store: VectorStore)
    
    def ingest_document(self, document: Document) -> None
    def generate_embeddings(self, text: str) -> List[float]
    def chunk_document(self, document: Document) -> List[DocumentChunk]
    def store_embeddings(self, chunks: List[DocumentChunk], embeddings: List[List[float]]) -> None
```

**Document Chunking Strategy:**
- Chunk size: 1000 characters
- Chunk overlap: 200 characters
- Preserve markdown structure
- Use LangChain RecursiveCharacterTextSplitter

### 6. Vector Store Manager

**Purpose:** Interface with OpenSearch Serverless for vector operations

**Interface:**
```python
class VectorStoreManager:
    def __init__(self, opensearch_endpoint: str, index_name: str)
    
    def create_index(self, dimensions: int) -> None
    def upsert_vectors(self, vectors: List[VectorDocument]) -> None
    def similarity_search(self, query_vector: List[float], k: int) -> List[Document]
    def delete_by_source(self, repo: str, file_path: str) -> None
```

**Vector Document Schema:**
```python
{
    "id": "uuid",
    "vector": [float],  # 1536 dimensions for Titan embeddings
    "metadata": {
        "repo_url": str,
        "file_path": str,
        "chunk_index": int,
        "last_modified": str,
        "document_type": "kiro_doc",
        "source_type": "github"
    },
    "text": str
}
```

### 7. Query Handler (Agent Lambda)

**Purpose:** Process user queries using RAG pipeline

**Interface:**
```python
class QueryHandler:
    def __init__(self, rag_chain: RetrievalQA, config: Config)
    
    def handle_query(self, query: str) -> QueryResponse
    def validate_query(self, query: str) -> bool
    def format_response(self, llm_response: str, sources: List[Document]) -> QueryResponse
```

**API Gateway Integration:**
```
POST /query
Request:
{
    "query": "How does the authentication system work?",
    "max_results": 5  # optional
}

Response:
{
    "answer": "The authentication system uses...",
    "sources": [
        {
            "repo": "github.com/org/repo1",
            "file_path": ".kiro/architecture/auth.md",
            "relevance_score": 0.92
        }
    ],
    "timestamp": "2025-12-09T10:30:00Z"
}
```

### 8. RAG Chain

**Purpose:** Orchestrate retrieval and generation using LangChain

**Interface:**
```python
class ArchonRAGChain:
    def __init__(self, llm: Bedrock, retriever: VectorStoreRetriever, 
                 prompt_template: PromptTemplate)
    
    def invoke(self, query: str) -> Dict[str, Any]
    def get_relevant_documents(self, query: str) -> List[Document]
    def generate_response(self, query: str, context: List[Document]) -> str
```

**Prompt Template:**
```
You are Archon, a system engineering expert assistant. Your role is to help engineers 
and agents understand product architecture by providing accurate information from 
documentation.

Context from documentation:
{context}

Question: {question}

Provide a clear, accurate answer based on the documentation. If the documentation 
doesn't contain enough information to answer fully, acknowledge this. Always cite 
the specific documents you reference.

Answer:
```

### 9. CDK Infrastructure

**Purpose:** Define and deploy AWS infrastructure

**Structure:**
```typescript
// lib/config-loader.ts
export class ConfigLoader {
  static loadConfig(configPath: string): ArchonConfig
}

// lib/cron-stack.ts
export class ArchonCronStack extends Stack {
  constructor(scope: Construct, id: string, config: ArchonConfig)
  // Creates: EventBridge, Lambda, DynamoDB, IAM
}

// lib/agent-stack.ts
export class ArchonAgentStack extends Stack {
  constructor(scope: Construct, id: string, config: ArchonConfig)
  // Creates: API Gateway, Lambda, IAM
}

// lib/shared-resources.ts
export class ArchonSharedResources extends Stack {
  constructor(scope: Construct, id: string, config: ArchonConfig)
  // Creates: OpenSearch Serverless collection
}

// bin/archon.ts
const app = new App();
const config = ConfigLoader.loadConfig('./config/config.yaml');

new ArchonSharedResources(app, 'ArchonShared', config);
new ArchonCronStack(app, 'ArchonCron', config);
new ArchonAgentStack(app, 'ArchonAgent', config);
```

## Data Models

### Document
```python
@dataclass
class Document:
    repo_url: str
    file_path: str
    content: str
    sha: str
    last_modified: datetime
    document_type: str = "kiro_doc"
    source_type: str = "github"
```

### DocumentChunk
```python
@dataclass
class DocumentChunk:
    document: Document
    chunk_index: int
    text: str
    start_char: int
    end_char: int
```

### RepositoryConfig
```python
@dataclass
class RepositoryConfig:
    url: str
    branch: str
    paths: List[str]
```

### QueryResponse
```python
@dataclass
class QueryResponse:
    answer: str
    sources: List[SourceReference]
    timestamp: datetime
    query: str
```

### SourceReference
```python
@dataclass
class SourceReference:
    repo: str
    file_path: str
    relevance_score: float
    chunk_text: Optional[str] = None
```

### MonitoringResult
```python
@dataclass
class MonitoringResult:
    repositories_checked: int
    documents_processed: int
    documents_updated: int
    errors: List[str]
    execution_time: float
```

## Correctness Properties

*A property is a characteristic or behavior that should hold true across all valid executions of a system—essentially, a formal statement about what the system should do. Properties serve as the bridge between human-readable specifications and machine-verifiable correctness guarantees.*

