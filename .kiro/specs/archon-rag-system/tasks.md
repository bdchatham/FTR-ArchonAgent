# Implementation Plan

- [x] 1. Set up project structure and configuration management
  - Create directory structure for CDK infrastructure, Lambda functions, and shared utilities
  - Implement ConfigManager class to load and validate YAML configuration files
  - Define configuration schema with repositories, infrastructure, and model parameters
  - Create example config.yaml with sample repository configurations
  - _Requirements: 1.1, 1.2, 8.1_

- [x] 1.1 Write property test for configuration parsing
  - **Feature: archon-rag-system, Property 1: Configuration parsing completeness**
  - **Validates: Requirements 1.1**

- [x] 1.2 Write property test for GitHub URL validation
  - **Feature: archon-rag-system, Property 2: GitHub URL validation**
  - **Validates: Requirements 1.2**

- [x] 2. Implement GitHub client using PyGithub
  - Create GitHubClient class wrapping PyGithub's Github class
  - Implement methods to fetch repository contents and file content using PyGithub API
  - Add URL parsing to extract org/repo from GitHub URLs
  - Add repository access verification using PyGithub
  - Implement error handling for API failures (404, 403, timeouts)
  - Note: PyGithub handles rate limiting automatically
  - _Requirements: 3.1, 3.3, 3.5, 9.1, 9.2, 9.3_

- [x] 2.1 Write property test for independent repository processing
  - **Feature: archon-rag-system, Property 3: Independent repository processing**
  - **Validates: Requirements 1.4**

- [x] 2.2 Write property test for error isolation
  - **Feature: archon-rag-system, Property 4: Error isolation in multi-repository monitoring**
  - **Validates: Requirements 1.5**

- [x] 2.3 Write property test for API error resilience
  - **Feature: archon-rag-system, Property 8: API error resilience**
  - **Validates: Requirements 3.5**

- [x] 2.4 Write property test for rate limit compliance
  - **Feature: archon-rag-system, Property 21: Rate limit compliance**
  - **Validates: Requirements 9.3**

- [x] 3. Implement change tracking with DynamoDB
  - Create ChangeTracker class to interface with DynamoDB
  - Implement methods to get last known SHA, update SHA, and detect changes
  - Define DynamoDB table schema with partition key and attributes
  - Add error handling for DynamoDB throttling and connection errors
  - _Requirements: 3.2, 4.4_

- [x] 3.1 Write property test for document update replacement
  - **Feature: archon-rag-system, Property 11: Document update replaces previous version**
  - **Validates: Requirements 4.4**

- [x] 4. Implement document ingestion pipeline
  - Create IngestionPipeline class to process documents
  - Implement document chunking using LangChain RecursiveCharacterTextSplitter (1000 chars, 200 overlap)
  - Integrate AWS Bedrock for embedding generation (amazon.titan-embed-text-v1)
  - Implement retry logic with exponential backoff for embedding failures
  - Add document content extraction and preprocessing
  - _Requirements: 4.1, 4.2, 4.3, 4.5_

- [x] 4.1 Write property test for embedding dimension consistency
  - **Feature: archon-rag-system, Property 9: Embedding dimension consistency**
  - **Validates: Requirements 4.1**

- [x] 4.2 Write property test for metadata completeness
  - **Feature: archon-rag-system, Property 10: Metadata completeness in vector storage**
  - **Validates: Requirements 4.2, 4.3**

- [x] 4.3 Write property test for embedding retry with backoff
  - **Feature: archon-rag-system, Property 12: Embedding generation retry with backoff**
  - **Validates: Requirements 4.5**

- [x] 4.4 Write property test for document type metadata
  - **Feature: archon-rag-system, Property 23: Document type metadata presence**
  - **Validates: Requirements 10.3**

- [x] 5. Implement vector store manager with OpenSearch
  - Create VectorStoreManager class to interface with OpenSearch Serverless
  - Implement index creation with vector field configuration (1536 dimensions)
  - Add upsert_vectors method to store embeddings with metadata
  - Implement similarity_search method with k-nearest neighbors
  - Add delete_by_source method for document updates
  - Integrate with LangChain OpenSearch vector store
  - _Requirements: 4.2, 4.3, 4.4, 6.2_

- [x] 5.1 Write property test for similarity search ordering
  - **Feature: archon-rag-system, Property 16: Similarity search ordering**
  - **Validates: Requirements 6.2**

- [x] 6. Implement document monitor Lambda function
  - Create DocumentMonitor class to orchestrate monitoring workflow
  - Implement execute method to check all configured repositories
  - Add logic to fetch repository contents, detect changes, and process documents
  - Create Lambda handler function with proper initialization
  - Implement MonitoringResult data class to track execution metrics
  - Add comprehensive error handling and logging
  - _Requirements: 3.1, 3.3, 3.4, 3.5_

- [x] 6.1 Write property test for complete repository scanning
  - **Feature: archon-rag-system, Property 5: Complete repository scanning**
  - **Validates: Requirements 3.1**

- [x] 6.2 Write property test for document content extraction
  - **Feature: archon-rag-system, Property 6: Document content extraction**
  - **Validates: Requirements 3.3**

- [x] 6.3 Write property test for monitoring result completeness
  - **Feature: archon-rag-system, Property 7: Monitoring result completeness**
  - **Validates: Requirements 3.4**

- [x] 6.4 Write property test for public repository restriction
  - **Feature: archon-rag-system, Property 19: Public repository restriction**
  - **Validates: Requirements 9.1**

- [x] 6.5 Write property test for permission error handling
  - **Feature: archon-rag-system, Property 20: Permission error handling**
  - **Validates: Requirements 9.2**

- [ ] 7. Implement RAG chain with LangChain
  - Create ArchonRAGChain class using LangChain RetrievalQA
  - Integrate AWS Bedrock LLM (anthropic.claude-3-haiku-20240307)
  - Define prompt template for Archon system engineering expert persona
  - Implement retriever using VectorStoreManager
  - Add methods to get relevant documents and generate responses
  - Configure LangChain to return source documents with responses
  - _Requirements: 6.1, 6.2, 6.3, 6.4, 7.1, 7.2, 7.3, 7.4, 7.5_

- [ ] 7.1 Write property test for query embedding generation
  - **Feature: archon-rag-system, Property 15: Query embedding generation**
  - **Validates: Requirements 6.1**

- [ ] 7.2 Write property test for context inclusion in LLM prompt
  - **Feature: archon-rag-system, Property 17: Context inclusion in LLM prompt**
  - **Validates: Requirements 6.3**

- [ ] 8. Implement query handler Lambda function
  - Create QueryHandler class to process API requests
  - Implement query validation (non-empty, reasonable length)
  - Add handle_query method to orchestrate RAG pipeline
  - Implement format_response to structure QueryResponse with sources
  - Create Lambda handler function with API Gateway integration
  - Add error handling for invalid queries and processing failures
  - _Requirements: 5.1, 5.2, 5.3, 5.4, 6.5_

- [ ] 8.1 Write property test for query input validation
  - **Feature: archon-rag-system, Property 13: Query input validation**
  - **Validates: Requirements 5.2**

- [ ] 8.2 Write property test for invalid query error responses
  - **Feature: archon-rag-system, Property 14: Invalid query error responses**
  - **Validates: Requirements 5.4**

- [ ] 8.3 Write property test for source reference completeness
  - **Feature: archon-rag-system, Property 18: Source reference completeness**
  - **Validates: Requirements 6.5**

- [ ] 9. Define data models and schemas
  - Create Document, DocumentChunk, RepositoryConfig dataclasses
  - Create QueryResponse, SourceReference, MonitoringResult dataclasses
  - Add validation methods and serialization logic
  - Implement proper type hints throughout
  - _Requirements: 4.2, 4.3, 6.5_

- [ ] 10. Implement shared resources CDK stack (TypeScript)
  - Create ArchonSharedResources stack class following AWS Well-Architected Framework
  - Define OpenSearch Serverless collection with vector search configuration
  - Configure index with 1536-dimension vector field
  - Set up least-privilege IAM policies for Lambda access to OpenSearch
  - Enable encryption at rest for OpenSearch
  - Add CloudFormation outputs for resource ARNs
  - Apply resource tags (Environment, Project, Owner)
  - _Requirements: 2.1, 2.2, 4.2_

- [ ] 11. Implement cron job CDK stack (TypeScript)
  - Create ArchonCronStack class following AWS Well-Architected Framework
  - Define EventBridge scheduled rule with configurable cron expression
  - Create Lambda function resource for document monitor with proper memory/timeout settings
  - Define DynamoDB table for change tracking with encryption enabled
  - Configure least-privilege IAM roles with specific resource ARNs for Bedrock, OpenSearch, DynamoDB
  - Set up CloudWatch log groups with retention policies and alarms for errors
  - Add environment variables for configuration
  - Apply resource tags (Environment, Project, Owner)
  - _Requirements: 2.1, 2.2, 3.1, 3.2_

- [ ] 12. Implement agent CDK stack (TypeScript)
  - Create ArchonAgentStack class following AWS Well-Architected Framework
  - Define API Gateway REST API with /query endpoint and throttling limits
  - Create Lambda function resource for query handler with proper memory/timeout settings
  - Configure Lambda integration with API Gateway
  - Set up least-privilege IAM roles with specific resource ARNs for Bedrock and OpenSearch
  - Configure CloudWatch log groups with retention policies and alarms for errors/latency
  - Add CORS configuration for API Gateway
  - Add environment variables for configuration
  - Apply resource tags (Environment, Project, Owner)
  - _Requirements: 2.1, 2.3, 5.1_

- [ ] 13. Implement CDK configuration loader (TypeScript)
  - Create ConfigLoader utility class for CDK
  - Implement YAML parsing for infrastructure configuration
  - Add validation for required fields and valid values
  - Create TypeScript interfaces for configuration structure
  - Add error handling for missing or invalid configuration
  - _Requirements: 1.1, 1.3, 8.1, 8.3_

- [ ] 14. Create CDK app entry point (TypeScript)
  - Create bin/archon.ts with CDK app initialization
  - Load configuration using ConfigLoader
  - Instantiate all three stacks (Shared, Cron, Agent)
  - Configure stack dependencies (Shared → Cron/Agent)
  - Add stack tags for resource organization (Environment, Project, Owner, CostCenter)
  - _Requirements: 2.1, 2.4, 8.3_

- [ ] 15. Set up Lambda deployment packages
  - Create requirements.txt for Python dependencies (langchain, boto3, hypothesis, etc.)
  - Configure Lambda layers for shared dependencies
  - Set up proper directory structure for Lambda code
  - Add Dockerfile for Lambda container images (if needed)
  - Configure CDK to bundle Lambda code correctly
  - _Requirements: 2.2, 2.3_

- [ ] 16. Implement logging and monitoring
  - Add structured logging throughout all components
  - Implement CloudWatch custom metrics for key operations
  - Add X-Ray tracing instrumentation
  - Create CloudWatch dashboard for monitoring
  - Configure alarms for errors and performance issues
  - _Requirements: 3.4, 5.3_

- [ ] 17. Create deployment scripts and documentation
  - Write deployment script (deploy.sh) for CDK deployment
  - Create README.md with setup and deployment instructions
  - Document configuration file format and options
  - Add troubleshooting guide for common issues
  - Create architecture diagrams and documentation
  - _Requirements: 8.1, 8.4_

- [ ] 18. Checkpoint - Ensure all tests pass
  - Ensure all tests pass, ask the user if questions arise.
